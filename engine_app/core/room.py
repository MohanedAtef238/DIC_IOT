import asyncio
import json
import logging
import random, time
from utils.temperature_calculator import calc_temp

log = logging.getLogger("room")


class Room:
    def __init__(self, floor, room_num, env):
        self.floor = floor
        self.room_num = room_num
        self.id = f"bldg_01-floor_{floor:02d}-room_{room_num:03d}"
        self.base_topic = f"campus/bldg_01/floor_{floor:02d}/room_{room_num:03d}"

        # see .env
        self.alpha = env["alpha"]
        self.beta  = env["beta"]
        self.outside = env["outside_temp"]
        self.interval = env["publish_interval"]

        # sensor readings, the defaults at least.
        self.temp = 22.0
        self.humidity = 50.0
        self.target = 22.0
        self.hvac = "OFF"
        self.occ = False
        self.lux = 200
        self.light_threshold = 300

    def tick(self):
        # this is oone simulation step with thermal model + lighting + humidity
        hvac_pwr = {"ON": 1.0, "ECO": 0.5}.get(self.hvac, 0.0)
        self.temp = calc_temp(self.temp, self.outside, self.alpha, self.beta, hvac_pwr, self.target, self.occ)

        self.humidity += 0.05 if self.occ else -0.02
        self.humidity = round(max(20, min(90, self.humidity)), 2) 

        # if someone's in the room, lights must be above threshold, and this way if there is already light from reading from sensor, we wouldnt have to change it. things like an open window and what not. 
        if self.occ:
            self.lux = max(self.lux, self.light_threshold)
        else:
            self.lux = 0

    def payload(self):
        return {
            "room_id": self.id,
            "ts": int(time.time()),
            "temperature": self.temp,
            "humidity": self.humidity,
            "occupancy": self.occ,
            "ambient_light": self.lux,
            "hvac_status": self.hvac,
        }

    async def run_loop(self, mqtt):
        #random stagger so we dont hammer the broker with 200 publishes at t=0
        await asyncio.sleep(random.uniform(0, self.interval))

        while True:
            t0 = time.perf_counter()
            self.tick()

            ts = int(time.time())
            base = self.base_topic + "/sensor"
            await mqtt.publish(f"{base}/temperature", json.dumps({"value": self.temp, "ts": ts}))
            await mqtt.publish(f"{base}/humidity",    json.dumps({"value": self.humidity, "ts": ts}))
            await mqtt.publish(f"{base}/occupancy",   json.dumps({"value": self.occ, "ts": ts}))
            await mqtt.publish(f"{base}/light",        json.dumps({"ambient": self.lux, "ts": ts}))

            await asyncio.sleep(max(0, self.interval - (time.perf_counter() - t0)))
