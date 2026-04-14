import asyncio
import json
import logging
import os, sys
import time
from dotenv import load_dotenv

from core.mqtt_room import MQTT_room
from core.coap_room import CoAP_room
from network.mqtt_client import MQTTClient
from network.topics import *
from storage.sqlite_store import SQLiteRoomStore


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", stream=sys.stdout)
log = logging.getLogger("engine")


def get_env():
    load_dotenv()
    conf = {}
    conf["floors"]    = int(os.environ["NUM_FLOORS"])
    conf["per_floor"] = int(os.environ["ROOMS_PER_FLOOR"])
    conf["alpha"]     = float(os.environ["ALPHA"])
    conf["beta"]      = float(os.environ["BETA"])
    conf["outside_temp"]  = float(os.environ["OUTSIDE_TEMP"])
    conf["default_target"] = float(os.environ["DEFAULT_TARGET_TEMP"])
    conf["health_interval"] = int(os.environ.get("HEALTH_INTERVAL",30))
    conf["mqtt_host"] = os.environ["MQTT_HOST"]
    conf["mqtt_port"] = int(os.environ["MQTT_PORT"])
    conf["sqlite_db_path"] = os.environ.get("SQLITE_DB_PATH", "/data/campus.db")
    conf["publish_interval"] = int(os.environ.get("PUBLISH_INTERVAL",5))
    conf["mqtt_ca_cert"] = os.environ.get("MQTT_CA_CERT")  # None = plain TCP
    conf["coap_dtls_enabled"] = os.environ.get("COAP_DTLS_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}
    conf["dtls_psk"] = None
    if not conf["coap_dtls_enabled"]:
        log.warning("COAP_DTLS_ENABLED is false; CoAP rooms will run plain UDP")
        return conf
    # Prefer JSON file (shared with test scripts) so keys always match.
    dtls_psk_file = os.environ.get("DTLS_PSK_FILE", "/certs/dtls_psk.json")
    if os.path.isfile(dtls_psk_file):
        with open(dtls_psk_file) as f:
            d = json.load(f)
        conf["dtls_psk"] = {"psk_identity": d["psk_identity"], "psk_key_b64": d["psk_key_b64"]}
        log.info("loaded DTLS PSK from %s", dtls_psk_file)
    else:
        identity = os.environ.get("DTLS_PSK_IDENTITY")
        key_b64  = os.environ.get("DTLS_PSK_KEY_B64")
        if identity and key_b64:
            conf["dtls_psk"] = {"psk_identity": identity, "psk_key_b64": key_b64}
        else:
            log.warning("No DTLS PSK found — CoAP rooms will run plain")
    return conf


async def run_engine():
    env = get_env()
    nfloors = env["floors"]
    nrooms  = env["per_floor"]
    total = nfloors * nrooms

    log.info("booting campus sim — %d nodes (%dx%d), paired MQTT+CoAP", total, nfloors, nrooms)

    store = SQLiteRoomStore(env["sqlite_db_path"])
    store.connect()
    saved_states = store.load_room_states()

    # Each floor gets nrooms//2 MQTT rooms (odd slots) and nrooms//2 CoAP rooms (even slots).
    # Pairs are created together: MQTT at rm, CoAP at rm+1.
    mqtt_rooms = []
    coap_rooms = []
    for fl in range(1, nfloors + 1):
        for rm in range(1, nrooms, 2):
            mqtt_id = f"b01-f{fl:02d}-r{rm:03d}"
            coap_id = f"b01-f{fl:02d}-r{rm+1:03d}"
            mqtt_rooms.append(MQTT_room(fl, rm,     env, state=saved_states.get(mqtt_id)))
            coap_rooms.append(CoAP_room(fl, rm + 1, env, state=saved_states.get(coap_id)))

    all_rooms = mqtt_rooms + coap_rooms

    engine_broker = MQTTClient(env["mqtt_host"], env["mqtt_port"], ca_cert=env["mqtt_ca_cert"])
    state_flush_event = asyncio.Event()
    pending_fleet_acks = {}
    # Only MQTT rooms send applied-ack messages back over the broker.
    expected_mqtt_rooms = len(mqtt_rooms)

    async def handle_hvac_applied_ack(topic, payload):
        try:
            data = json.loads(payload)
            room_id = data["room_id"]
            command_id = data.get("command_id")
        except (json.JSONDecodeError, KeyError, TypeError):
            log.warning("invalid hvac applied ack from %s: %s", topic, payload)
            return

        acked_rooms = pending_fleet_acks.setdefault(command_id, set())
        acked_rooms.add(room_id)

        if len(acked_rooms) >= expected_mqtt_rooms:
            pending_fleet_acks.pop(command_id, None)
            state_flush_event.set()
            log.info("state persistence wake requested after fleet hvac command %s", command_id)

    async def handle_fleet_hvac_command(topic, payload):
        try:
            data = json.loads(payload)
            mode = str(data["hvac_mode"]).upper()
        except (json.JSONDecodeError, KeyError, TypeError):
            log.warning("invalid fleet hvac command from %s: %s", topic, payload)
            return

        updated = 0
        for room in coap_rooms:
            if await room.apply_hvac_command(mode):
                updated += 1

        if updated:
            state_flush_event.set()
            log.info("applied fleet hvac command %s to %d CoAP rooms", mode, updated)


    def persist_all_states():
        for room in all_rooms:
            state = room.state
            store.save_room_payload(
                {
                    "room_id": state["room_id"],
                    "temperature": state["last_temp"],
                    "humidity": state["last_humidity"],
                    "hvac_status": state["hvac_mode"],
                    "target_temp": state["target_temp"],
                    "lighting_dimmer": state["lighting_dimmer"],
                    "ts": state["last_update"],
                }
            )

    async def persist_states_loop():
        while True:
            try:
                await asyncio.wait_for(state_flush_event.wait(), timeout=30)
            except asyncio.TimeoutError:
                pass
            state_flush_event.clear()
            persist_all_states()
            log.info("persisted %d room states to sqlite", len(all_rooms))

    if not saved_states:
        persist_all_states()
        log.info("sqlite was empty; initialized %d rooms with default values", len(all_rooms))

    async def check_health():
        heartbeat_timeout = env["health_interval"]
        while True:
            now = int(time.time())
            slowest = max(all_rooms, key=lambda r: now - r.last_heartbeat)
            seconds_since = now - slowest.last_heartbeat
            if seconds_since >= heartbeat_timeout:
                log.warning(
                    "room %s missed heartbeat for %ds (timeout=%ds)",
                    slowest.id, seconds_since, heartbeat_timeout,
                )
            else:
                log.info(
                    "health check ok; slowest room %s last heartbeat %ds ago",
                    slowest.id, seconds_since,
                )
            await asyncio.sleep(env["health_interval"])



    # one persistence task + two tasks per room (room broker + room publish loop)
    engine_broker.subscribe(all_room_hvac_applied_ack_topics(), handle_hvac_applied_ack)
    engine_broker.subscribe(fleet_hvac_command_topic(), handle_fleet_hvac_command)
    tasks = [
        asyncio.create_task(engine_broker.run()),
        asyncio.create_task(persist_states_loop()),
        asyncio.create_task(check_health()),
    ]
    for r in mqtt_rooms:
        tasks.append(asyncio.create_task(r.broker.run()))
        tasks.append(asyncio.create_task(r.run_loop()))
    for r in coap_rooms:
        tasks.append(asyncio.create_task(r.run_server()))
        tasks.append(asyncio.create_task(r.run_loop()))

    log.info("%d tasks launched, entering event loop", len(tasks))
    await asyncio.gather(*tasks)


if __name__ == "__main__":
    asyncio.run(run_engine())
