import asyncio
import logging
import os, sys
from dotenv import load_dotenv

from core.room import Room
from network.mqtt_client import MQTTClient

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
    broker.register_rooms(rooms)

    # each room gets its own async loop + one for the broker connection
    tasks = [asyncio.create_task(broker.run())]
    for r in rooms:
        tasks.append(asyncio.create_task(r.run_loop(broker)))

    log.info("%d tasks launched, entering event loop", len(tasks))
    await asyncio.gather(*tasks)


if __name__ == "__main__":
    asyncio.run(run_engine())
