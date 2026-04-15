import asyncio
import json
import logging
import random
import time
import psutil  # For CPU and memory usage
from network.mqtt_client import MQTTClient
from utils.temperature_calculator import calc_temp
from network.topics import *
log = logging.getLogger("mqtt_room")

class MQTT_room:
    def __init__(self, floor, room_num, env, state=None):
        self.last_heartbeat = int(time.time())

        self.floor = floor
        self.room_num = room_num
        self.id = f"b01-f{floor:02d}-r{room_num:03d}"
        self.base_topic = room_base_topic(floor, room_num)

        # see .env
        self.alpha = env["alpha"]
        self.beta = env["beta"]
        self.outside = env["outside_temp"]
        self.interval = env["publish_interval"]
        self.fault_probability = env.get("fault_probability", 0.01)  # 1% chance of fault per tick

        # Performance metrics
        self.performance_metrics = {
            "tick_duration": [],
            "event_loop_latency": [],
            "cpu_usage": [],
            "memory_usage": [],
        }

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
        self.dimmer = 75  # lighting dimmer %, 0-100
        self.lux = round(self.dimmer / 100 * 1000)
        self.light_threshold = 300

        if state and 'lighting_dimmer' in state:
            self.dimmer = state['lighting_dimmer']
            self.lux = round(self.dimmer / 100 * 1000)
        self.state = state if state is not None else {}
        self._sync_state()
        self.broker = MQTTClient(env["mqtt_host"], env["mqtt_port"], ca_cert=env.get("mqtt_ca_cert"))
        self.register_actuator_subscriptions()

        # Fault state
        self.frozen_temp = None
        self.frozen_humidity = None
        self.frozen_lux = None
        self.frozen_occ = None
        self.fault_active = False
        self.fault_type = None
        self.fault_duration = 0
        self.fault_start_time = 0

    def _sync_state(self):
        self.state["room_id"] = self.id
        self.state["last_temp"] = self.temp
        self.state["last_humidity"] = self.humidity
        self.state["target_temp"] = self.target
        self.state["hvac_mode"] = self.hvac
        self.state["lighting_dimmer"] = self.dimmer
        self.state["last_update"] = int(time.time())

    def refresh_state(self):
        self._sync_state()
    
    async def publish_heartbeat(self):
        self.last_heartbeat = int(time.time())
        self._sync_state()
        await self.broker.publish_json(
            room_heartbeat(),
            {
                "room_id": self.id,
                "ts": self.last_heartbeat,
            }
        )


    def register_actuator_subscriptions(self):
        self.register_hvac_subscription()
        self.register_light_dimmer_subscription()

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

    def register_light_dimmer_subscription(self):
        async def handle_light_dimmer_command(topic, payload):
            try:
                data = json.loads(payload)
                dimmer_value = int(data["lighting_dimmer"])
            except (json.JSONDecodeError, KeyError, TypeError, ValueError):
                log.warning("invalid light dimmer command from %s", topic)
                return

            if not 0 <= dimmer_value <= 100:
                log.warning("light dimmer out of range for %s: %s", self.id, dimmer_value)
                return

            self.dimmer = dimmer_value
            self.refresh_state()
            command_id = data.get("command_id")
            await self.broker.publish_json(
                room_light_dimmer_applied_ack_topic(self.base_topic),
                {
                    "room_id": self.id,
                    "lighting_dimmer": self.dimmer,
                    "command_id": command_id,
                },
            )
            log.info("room light dimmer updated %s -> %s", self.id, dimmer_value)

        self.broker.subscribe(room_light_dimmer_command_topic(self.base_topic), handle_light_dimmer_command)

    def _inject_fault(self):
        if random.random() < self.fault_probability:
            fault_type = random.choice(["sensor_drift", "frozen_sensor", "telemetry_delay", "node_dropout"])
            self.fault_type = fault_type
            self.fault_duration = random.randint(5, 30)  # Fault lasts 5-30 seconds
            self.fault_start_time = time.time()
            self.fault_active = True
            log.warning(f"Fault injected in {self.id}: {fault_type} for {self.fault_duration}s")

    def _clear_fault(self):
        if self.fault_active and (time.time() - self.fault_start_time) > self.fault_duration:
            self.fault_active = False
            self.fault_type = None
            self.frozen_temp = None
            self.frozen_humidity = None
            self.frozen_lux = None
            self.frozen_occ = None
            log.info(f"Fault cleared in {self.id}")

    def tick(self):
        # self._inject_fault()
        # self._clear_fault()

        # if self.fault_active:
        #     if self.fault_type == "sensor_drift":
        #         self.temp += random.uniform(-0.5, 0.5)  # Drift temperature
        #         self.humidity += random.uniform(-1, 1)  # Drift humidity
        #     elif self.fault_type == "frozen_sensor":
        #         if self.frozen_temp is None:
        #             self.frozen_temp = self.temp
        #             self.frozen_humidity = self.humidity
        #             self.frozen_lux = self.lux
        #             self.frozen_occ = self.occ
        #         assert self.frozen_temp is not None
        #         assert self.frozen_humidity is not None
        #         assert self.frozen_lux is not None
        #         assert self.frozen_occ is not None
        #         self.temp = self.frozen_temp
        #         self.humidity = self.frozen_humidity
        #         self.lux = self.frozen_lux
        #         self.occ = self.frozen_occ
        #     # For telemetry_delay and node_dropout, handled in run_loop

        # Normal tick logic
        hvac_pwr = {"ON": 1.0, "ECO": 0.5}.get(self.hvac, 0.0)
        self.temp = calc_temp(self.temp, self.outside, self.alpha, self.beta, hvac_pwr, self.target, self.occ)

        self.humidity += 0.05 if self.occ else -0.02
        self.humidity = round(max(20, min(90, self.humidity)), 2)

        if self.occ:
            self.lux = max(self.lux, self.light_threshold)

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
                "lighting_dimmer": self.dimmer,
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
        # Random stagger to avoid thundering herd
        await asyncio.sleep(random.uniform(0, self.interval))

        while True:
            tick_start = time.perf_counter()
            self.tick()
            tick_end = time.perf_counter()
            tick_duration_ms = (tick_end - tick_start) * 1000.0
            self.performance_metrics["tick_duration"].append(tick_duration_ms)

            # Measure CPU and memory usage
            cpu_usage = psutil.cpu_percent(interval=None)
            memory_usage = psutil.virtual_memory().percent
            self.performance_metrics["cpu_usage"].append(cpu_usage)
            self.performance_metrics["memory_usage"].append(memory_usage)

            # Log performance metrics every 10 ticks
            if len(self.performance_metrics["tick_duration"]) % 10 == 0:
                avg_tick_duration = sum(self.performance_metrics["tick_duration"][-10:]) / 10
                avg_cpu_usage = sum(self.performance_metrics["cpu_usage"][-10:]) / 10
                avg_memory_usage = sum(self.performance_metrics["memory_usage"][-10:]) / 10
                log.info(
                    f"Performance metrics for {self.id}: "
                    f"Avg tick duration: {avg_tick_duration:.4f}ms, "
                    f"Avg CPU usage: {avg_cpu_usage:.2f}%, "
                    f"Avg memory usage: {avg_memory_usage:.2f}%"
                )

            # if self.fault_active and self.fault_type == "telemetry_delay":
            #     await asyncio.sleep(random.uniform(1, 5))  # Delay telemetry
            # elif self.fault_active and self.fault_type == "node_dropout":
            #     await asyncio.sleep(self.interval)  # Skip publishing
            #     continue

            for topic, payload in self.sensor_messages():
                await self.broker.publish_json(topic, payload)
                
            await self.publish_heartbeat()
            if self.room_num==7 and self.floor==3:
                await asyncio.sleep(40)

            # Calculate event loop latency
            loop_latency = time.perf_counter() - tick_start
            loop_latency_ms = loop_latency * 1000.0
            self.performance_metrics["event_loop_latency"].append(loop_latency_ms)

            await asyncio.sleep(max(0, self.interval - loop_latency))
