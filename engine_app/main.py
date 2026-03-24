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

    store = SQLiteRoomStore(env["sqlite_db_path"])
    store.connect()
    saved_states = store.load_room_states()

    rooms = []
    for fl in range(1, nfloors + 1):
        for rm in range(1, nrooms + 1):
            room_id = f"bldg_01-floor_{fl:02d}-room_{rm:03d}"
            rooms.append(Room(fl, rm, env, state=saved_states.get(room_id)))

    broker = MQTTClient(env["mqtt_host"], env["mqtt_port"])
    rooms_by_topic = {room.base_topic: room for room in rooms}
    state_flush_event = asyncio.Event()


    async def handle_room_payload(topic, payload):
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            log.warning("invalid room payload from %s", topic)
            return

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
            room.refresh_state()
            state_flush_event.set()

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
            log.info("states persisted")

    async def persist_states_loop():
        while True:
            try:
                await asyncio.wait_for(state_flush_event.wait(), timeout=30)
            except asyncio.TimeoutError:
                pass
            state_flush_event.clear()
            persist_all_states()
            log.info("persisted %d room states to sqlite", len(rooms))

    # broker.subscribe(all_room_payload_topics(), handle_room_payload)
    broker.subscribe(all_room_hvac_command_topics(), handle_hvac_command)

    # each room gets its own async loop + one for the broker connection
    tasks = [asyncio.create_task(broker.run()), asyncio.create_task(persist_states_loop())]
    for r in rooms:
        tasks.append(asyncio.create_task(r.run_loop(broker.publish_json)))

    log.info("%d tasks launched, entering event loop", len(tasks))
    await asyncio.gather(*tasks)


if __name__ == "__main__":
    asyncio.run(run_engine())

