import asyncio, json, logging
import aiomqtt

log = logging.getLogger("mqtt")

CMD_TOPIC = "campus/bldg_01/+/+/actuator/hvac"


class MQTTClient:
    def __init__(self, host, port):
        self.host = host
        self.port = port
        self.queue = asyncio.Queue()
        self.rooms = {}

    def register_rooms(self, rooms):
        # index rooms by base topic so we can route actuator commands
        for r in rooms:
            self.rooms[r.base_topic] = r

    async def publish(self, topic, payload):
        await self.queue.put((topic, payload))

    async def publish_loop(self, client):
        while True:
            t, p = await self.queue.get()
            await client.publish(t, payload=p)

    async def subscribe_loop(self, client):
        await client.subscribe(CMD_TOPIC)
        async for msg in client.messages:
            try:
                data = json.loads(msg.payload)
                mode = data["hvac_mode"].upper()
            except Exception:
                continue

            # strip /actuator/hvac to get the room's base topic
            key = str(msg.topic).replace("/actuator/hvac", "")
            room = self.rooms.get(key)
            if room and mode in ["ON", "OFF", "ECO"]:
                room.hvac = mode

    async def run(self):
        # reconnect loop - mosquitto might drop us sometimes during dev, due to memory limits, or some reported file parsing bug i found online. 
        while True:
            try:
                async with aiomqtt.Client(hostname=self.host, port=self.port) as c:
                    log.info("broker connected %s:%d", self.host, self.port)
                    async with asyncio.TaskGroup() as tg:
                        tg.create_task(self.publish_loop(c))
                        tg.create_task(self.subscribe_loop(c))
            except* aiomqtt.MqttError:
                await asyncio.sleep(5)
