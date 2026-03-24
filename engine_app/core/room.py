import asyncio
import json
import logging
import random, time
from network.mqtt_client import MQTTClient
from utils.temperature_calculator import calc_temp
from network.topics import (
    fleet_hvac_command_topic,
    room_base_topic,
    room_hvac_applied_ack_topic,
    room_hvac_command_topic,
    room_payload_topic,
    room_sensor_topic,
)

log = logging.getLogger("room")


class Room:
    def __init__(self, floor, room_num, env, state=None):
        self.floor = floor
        self.room_num = room_num
        self.id = f"b01-floor_{floor:02d}-room_{room_num:03d}"
        self.base_topic = room_base_topic(floor, room_num)

        # see .env
        self.alpha = env["alpha"]
        self.beta  = env["beta"]
        self.outside = env["outside_temp"]
        self.interval = env["publish_interval"]

        # sensor readings, the defaults at least.
        self.temp = 22.0
        self.humidity = 50.0
        self.target = env["default_target"]
        self.hvac = "OFF"

        if state:
            self.temp = state['last_temp']
            self.humidity = state['last_humidity']
            self.target = state['target_temp']
            self.hvac = str(state['hvac_mode']).upper()

        self.occ = False
        self.lux = 200
        self.light_threshold = 300
        self.state = state if state is not None else {}
        self._sync_state()
        self.broker = MQTTClient(env["mqtt_host"], env["mqtt_port"])
        self.register_hvac_subscription()

    def _sync_state(self):
        self.state["room_id"] = self.id
        self.state["last_temp"] = self.temp
        self.state["last_humidity"] = self.humidity
        self.state["target_temp"] = self.target
        self.state["hvac_mode"] = self.hvac
        self.state["last_update"] = int(time.time())

    def refresh_state(self):
        self._sync_state()

    def register_hvac_subscription(self):
        async def handle_hvac_command(topic, payload):
            try:
                data = json.loads(payload)
                mode = data["hvac_mode"].upper()
            except (json.JSONDecodeError, KeyError, AttributeError):
                log.warning("invalid hvac command from %s", topic)
                return

            if mode not in ["ON", "OFF", "ECO"]:
                log.warning("invalid hvac mode for %s: %s", self.id, mode)
                return

            self.hvac = mode
            self.refresh_state()
            command_id = data.get("command_id")
            await self.broker.publish_json(
                room_hvac_applied_ack_topic(self.base_topic),
                {
                    "room_id": self.id,
                    "hvac_mode": self.hvac,
                    "command_id": command_id,
                },
            )
            log.info("room hvac updated %s -> %s", self.id, mode)

        self.broker.subscribe(room_hvac_command_topic(self.base_topic), handle_hvac_command)
        self.broker.subscribe(fleet_hvac_command_topic(), handle_hvac_command)


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

        self._sync_state()

    def payload(self):
        return {
            "metadata": {
                "sensor_id": self.id,
                "building": "b01",
                "floor": self.floor,
                "room": self.room_num,
                "timestamp": int(time.time()),
            },
            "sensors": {
                "temperature": self.temp,
                "humidity": self.humidity,
                "occupancy": self.occ,
                "light_level": self.lux,
            },
            "actuators": {
                "hvac_mode": self.hvac.lower(),
            },
        }

    def sensor_messages(self):
        ts = int(time.time())
        return [
            (room_payload_topic(self.base_topic), self.payload()),
            (room_sensor_topic(self.base_topic, "temperature"), {"value": self.temp, "ts": ts}),
            (room_sensor_topic(self.base_topic, "humidity"), {"value": self.humidity, "ts": ts}),
            (room_sensor_topic(self.base_topic, "occupancy"), {"value": self.occ, "ts": ts}),
            (room_sensor_topic(self.base_topic, "light"), {"ambient": self.lux, "ts": ts}),
        ]

    async def run_loop(self):
        #random stagger so we dont hammer the broker with 200 publishes at t=0
        await asyncio.sleep(random.uniform(0, self.interval))

        while True:
            t0 = time.perf_counter()
            self.tick()

            for topic, payload in self.sensor_messages():
                await self.broker.publish_json(topic, payload)

            await asyncio.sleep(max(0, self.interval - (time.perf_counter() - t0)))
