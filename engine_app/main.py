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


load_dotenv()


_log_level_name = os.environ.get("LOG_LEVEL", "INFO").strip().upper()
_log_level = getattr(logging, _log_level_name, logging.INFO)
logging.basicConfig(level=_log_level, format="%(asctime)s %(levelname)s %(message)s", stream=sys.stdout)
log = logging.getLogger("engine")


def get_env():
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
    conf["mqtt_client_cert"] = os.environ.get("MQTT_CLIENT_CERT")  # client cert for mTLS
    conf["mqtt_client_key"] = os.environ.get("MQTT_CLIENT_KEY")    # client key for mTLS
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
    room_counter = 1
    for fl in range(1, nfloors + 1):
        for _ in range(1, nrooms, 2):
            mqtt_id = f"b01-f{fl:02d}-r{room_counter:03d}"
            coap_id = f"b01-f{fl:02d}-r{room_counter+1:03d}"
            mqtt_rooms.append(MQTT_room(fl, room_counter,     env, state=saved_states.get(mqtt_id)))
            coap_rooms.append(CoAP_room(fl, room_counter + 1, env, state=saved_states.get(coap_id)))
            room_counter += 2

    all_rooms = mqtt_rooms + coap_rooms

    engine_broker = MQTTClient(
        env["mqtt_host"], env["mqtt_port"],
        ca_cert=env["mqtt_ca_cert"],
        client_cert=env.get("mqtt_client_cert"),
        client_key=env.get("mqtt_client_key"),
    )
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

    async def handle_ota_update(topic, payload):
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            log.warning("invalid OTA JSON from %s", topic)
            return

        # Determine target from topic
        # campus/b01/ota/config -> global
        # campus/b01/f05/ota -> floor 05
        # campus/b01/f05/r010/ota -> room b01-f05-r010
        
        parts = topic.split('/')
        target_floor = None
        target_room_id = None
        
        if len(parts) == 4 and parts[2] == "ota" and parts[3] == "config":
            # Global
            pass 
        elif len(parts) == 4 and parts[2].startswith('f') and parts[3] == "ota":
            # Floor
            target_floor = int(parts[2][1:])
        elif len(parts) == 5 and parts[4] == "ota":
            # Room
            target_room_id = f"b01-{parts[2]}-{parts[3]}"
        else:
            log.warning("unrecognized OTA topic structure: %s", topic)
            return

        # Parse config_data string into dict, then add target_version
        import json as _json
        try:
            config_dict = _json.loads(data["config_data"])
        except (KeyError, _json.JSONDecodeError, TypeError):
            log.warning("OTA payload missing or invalid config_data from %s", topic)
            return
        config_dict["version"] = str(data.get("target_version", ""))

        # Also filter by "target" field in payload if present
        payload_target = data.get("target", "all")

        updated = 0
        for r in all_rooms:
            match = True
            if target_floor is not None and r.floor != target_floor:
                match = False
            if target_room_id is not None:
                clean_target_room_id = target_room_id.replace("-COAP", "").replace("-MQTT", "")
                if r.id != clean_target_room_id:
                    match = False
            # If no topic-level targeting, use payload target field
            if target_floor is None and target_room_id is None:
                clean_payload_target = payload_target.replace("-COAP", "").replace("-MQTT", "")
                if clean_payload_target not in ("all", r.id, f"floor_{r.floor:02d}"):
                    match = False

            if match:
                if r.apply_ota_parameters(config_dict):
                    updated += 1

        if updated:
            state_flush_event.set()
            log.info("OTA update from %s applied to %d rooms", topic, updated)




    async def handle_individual_hvac_command(topic, payload):
        # Handles campus/b01/cmd/b01-f01-r002 (with or without -COAP)
        parts = topic.split('/')
        device_id = parts[-1].replace("-COAP", "").replace("-MQTT", "")
        
        try:
            data = json.loads(payload)
            mode = str(data["hvac_mode"]).upper()
        except: return

        for room in coap_rooms:
            if room.id == device_id:
                if await room.apply_hvac_command(mode):
                    state_flush_event.set()
                    log.info("Proxied MQTT HVAC command %s to CoAP room %s", mode, room.id)
                break


    async def handle_individual_dimmer_command(topic, payload):
        # campus/b01/f01/r002/actuator/light_dimmer
        parts = topic.split('/')
        floor_str = parts[2]
        room_str = parts[3]
        device_id = f"b01-{floor_str}-{room_str}"
        
        try:
            data = json.loads(payload)
            value = int(data["lighting_dimmer"])
        except: return

        for room in coap_rooms:
            if room.id == device_id:
                if await room.apply_light_dimmer_command(value):
                    state_flush_event.set()
                    log.info("Proxied MQTT Dimmer command %d to CoAP room %s", value, room.id)
                break
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
    engine_broker.subscribe(ota_global_topic(), handle_ota_update)
    engine_broker.subscribe(ota_floor_wildcard(), handle_ota_update)
    engine_broker.subscribe(ota_room_wildcard(), handle_ota_update)
    engine_broker.subscribe('campus/b01/cmd/+', handle_individual_hvac_command)
    engine_broker.subscribe('campus/b01/+/+/actuator/light_dimmer', handle_individual_dimmer_command)
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
