import asyncio, json, logging
import aiomqtt

log = logging.getLogger("mqtt")


def _topic_matches(topic_filter, topic):
    filter_parts = topic_filter.split("/")
    topic_parts = topic.split("/")

    if len(filter_parts) != len(topic_parts):
        return False

    for expected, actual in zip(filter_parts, topic_parts):
        if expected == "+":
            continue
        if expected != actual:
            return False

    return True


class MQTTClient:
    def __init__(self, host, port):
        self.host = host
        self.port = port
        self.queue = asyncio.Queue()
        self.subscriptions = []

    def subscribe(self, topic_filter, handler):
        self.subscriptions.append((topic_filter, handler))

    async def publish(self, topic, payload):
        await self.queue.put((topic, payload))

    async def publish_json(self, topic, payload):
        await self.publish(topic, json.dumps(payload))

    async def publish_loop(self, client):
        while True:
            t, p = await self.queue.get()
            await client.publish(t, payload=p, qos=2)

    async def subscribe_loop(self, client):
        for topic_filter, _ in self.subscriptions:
            await client.subscribe(topic_filter, qos=2)

        async for msg in client.messages:
            topic = str(msg.topic)
            payload = msg.payload.decode()

            for topic_filter, handler in self.subscriptions:
                if _topic_matches(topic_filter, topic):
                    await handler(topic, payload)

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
