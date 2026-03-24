import asyncio
import json
import logging
import os, sys
import time
from dotenv import load_dotenv

from core.room import Room
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
    return conf


async def run_engine():
    env = get_env()
    nfloors = env["floors"]
    nrooms  = env["per_floor"]
    total = nfloors * nrooms

    log.info("booting campus sim — %d nodes (%dx%d)", total, nfloors, nrooms)

    store = SQLiteRoomStore(env["sqlite_db_path"])
    store.connect()
    saved_states = store.load_room_states()

    rooms = []
    for fl in range(1, nfloors + 1):
        for rm in range(1, nrooms + 1):
            room_id = f"bldg_01-floor_{fl:02d}-room_{rm:03d}"
            rooms.append(Room(fl, rm, env, state=saved_states.get(room_id)))

    engine_broker = MQTTClient(env["mqtt_host"], env["mqtt_port"])
    state_flush_event = asyncio.Event()
    pending_fleet_acks = {}
    expected_rooms = len(rooms)

    room_index_by_id = {room.id: index for index, room in enumerate(rooms)}
    last_heartbeat = [int(time.time())] * expected_rooms
    slowest_room_heartbeat = rooms[0].id

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

        if len(acked_rooms) >= expected_rooms:
            pending_fleet_acks.pop(command_id, None)
            state_flush_event.set()
            log.info("state persistence wake requested after fleet hvac command %s", command_id)


    def persist_all_states():
        for room in rooms:
            state = room.state
            store.save_room_payload(
                {
                    "room_id": state["room_id"],
                    "temperature": state["last_temp"],
                    "humidity": state["last_humidity"],
                    "hvac_status": state["hvac_mode"],
                    "target_temp": state["target_temp"],
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
            log.info("persisted %d room states to sqlite", len(rooms))
    async def handle_heartbeat(topic, payload):
        nonlocal slowest_room_heartbeat

        try:
            data = json.loads(payload)
            room_id = data["room_id"]
        except (json.JSONDecodeError, KeyError, TypeError):
            log.warning("invalid heartbeat from %s: %s", topic, payload)
            return

        room_index = room_index_by_id.get(room_id)
        if room_index is None:
            log.warning("heartbeat received for unknown room_id: %s", room_id)
            return

        last_heartbeat[room_index] = int(time.time())

        if room_id == slowest_room_heartbeat:
            slowest_index = last_heartbeat.index(min(last_heartbeat))
            slowest_room_heartbeat = rooms[slowest_index].id

    async def check_health():
        heartbeat_timeout = env["health_interval"]

        while True:
            slowest_index = room_index_by_id[slowest_room_heartbeat]
            seconds_since_last_heartbeat = int(time.time()) - last_heartbeat[slowest_index]

            if seconds_since_last_heartbeat >= heartbeat_timeout:
                log.warning(
                    "room %s missed heartbeat for %ds (timeout=%ds)",
                    slowest_room_heartbeat,
                    seconds_since_last_heartbeat,
                    heartbeat_timeout,
                )
                await asyncio.sleep(5)
            else:
                log.info(
                    "health check ok; slowest room %s last heartbeat %ds ago",
                    slowest_room_heartbeat,
                    seconds_since_last_heartbeat,
                )
            await asyncio.sleep(max(0, env["health_interval"] - seconds_since_last_heartbeat))



    # one persistence task + two tasks per room (room broker + room publish loop)
    engine_broker.subscribe(all_room_hvac_applied_ack_topics(), handle_hvac_applied_ack)
    engine_broker.subscribe(room_heartbeat(), handle_heartbeat)
    tasks = [
        asyncio.create_task(engine_broker.run()),
        asyncio.create_task(persist_states_loop()),
        asyncio.create_task(check_health()),
    ]
    for r in rooms:
        tasks.append(asyncio.create_task(r.broker.run()))
        tasks.append(asyncio.create_task(r.run_loop()))

    log.info("%d tasks launched, entering event loop", len(tasks))
    await asyncio.gather(*tasks)


if __name__ == "__main__":
    asyncio.run(run_engine())
