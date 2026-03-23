import asyncio
import json
import logging
import os, sys
from dotenv import load_dotenv

from core.room import Room
from network.mqtt_client import MQTTClient
from network.topics import all_room_hvac_command_topics, all_room_payload_topics
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
    conf["publish_interval"] = float(os.environ["PUBLISH_INTERVAL"])
    conf["mqtt_host"] = os.environ["MQTT_HOST"]
    conf["mqtt_port"] = int(os.environ["MQTT_PORT"])
    conf["sqlite_db_path"] = os.environ.get("SQLITE_DB_PATH", "/data/campus.db")
    return conf


async def run_engine():
    env = get_env()
    nfloors = env["floors"]
    nrooms  = env["per_floor"]
    total = nfloors * nrooms

    log.info("booting campus sim — %d nodes (%dx%d)", total, nfloors, nrooms)

    rooms = []
    for fl in range(1, nfloors + 1):
        for rm in range(1, nrooms + 1):
            rooms.append(Room(fl, rm, env))

    broker = MQTTClient(env["mqtt_host"], env["mqtt_port"])
    store = SQLiteRoomStore(env["sqlite_db_path"])
    store.connect()
    saved_states = store.load_room_states()
    rooms_by_topic = {room.base_topic: room for room in rooms}
    rooms_by_id = {room.id: room for room in rooms}

    for room_id, state in saved_states.items():
        room = rooms_by_id.get(room_id)
        if room is None:
            continue

        room.temp = state["last_temp"]
        room.humidity = state["last_humidity"]
        room.hvac = state["hvac_mode"]
        room.target = state["target_temp"]

    async def handle_room_payload(topic, payload):
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            log.warning("invalid room payload from %s", topic)
            return

        store.save_room_payload(data)
        log.info("room payload %s: %s", topic, data)

    async def handle_hvac_command(topic, payload):
        try:
            data = json.loads(payload)
            mode = data["hvac_mode"].upper()
        except (json.JSONDecodeError, KeyError, AttributeError):
            log.warning("invalid hvac command from %s", topic)
            return

        room = rooms_by_topic.get(topic.replace("/actuator/hvac", ""))
        if room and mode in ["ON", "OFF", "ECO"]:
            room.hvac = mode

    broker.subscribe(all_room_payload_topics(), handle_room_payload)
    broker.subscribe(all_room_hvac_command_topics(), handle_hvac_command)

    # each room gets its own async loop + one for the broker connection
    tasks = [asyncio.create_task(broker.run())]
    for r in rooms:
        tasks.append(asyncio.create_task(r.run_loop(broker.publish_json)))

    log.info("%d tasks launched, entering event loop", len(tasks))
    await asyncio.gather(*tasks)


if __name__ == "__main__":
    asyncio.run(run_engine())
