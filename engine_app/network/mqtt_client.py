import asyncio, json, logging, os, re, ssl
import aiomqtt

log = logging.getLogger("engine.mqtt")

# Regex to extract the floor number from a standard campus topic.
# e.g. "campus/b01/floor_03/room_005/payload" → "03"
_FLOOR_RE = re.compile(r"campus/b\d+/floor_(\d+)/")


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


def extract_floor_from_topic(topic):
    """Return the zero-padded floor string from a topic, or None."""
    m = _FLOOR_RE.search(topic)
    return m.group(1) if m else None


class MQTTClient:
    def __init__(self, host, port, ca_cert=None,
                 client_cert=None, client_key=None,
                 username=None, password=None,
                 expected_floor=None,
                 will=None):
        self.host = host
        self.port = port
        self.ca_cert = ca_cert
        self.client_cert = client_cert or os.environ.get("MQTT_CLIENT_CERT")
        self.client_key = client_key or os.environ.get("MQTT_CLIENT_KEY")
        self.username = username or os.environ.get("MQTT_USER")
        self.password = password or os.environ.get("MQTT_PASS")
        # If set, inbound messages are checked: topic floor must match this value.
        self.expected_floor = expected_floor
        self.will = will
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

            # Application-level floor validation (defense-in-depth)
            if self.expected_floor is not None:
                topic_floor = extract_floor_from_topic(topic)
                if topic_floor is not None and topic_floor != self.expected_floor:
                    log.warning(
                        "floor mismatch: expected %s but topic says %s therefore dropping %s",
                        self.expected_floor, topic_floor, topic,
                    )
                    continue

            for topic_filter, handler in self.subscriptions:
                if _topic_matches(topic_filter, topic):
                    await handler(topic, payload)

    async def run(self):
        # reconnect loop - mosquitto might drop us sometimes during dev, due to memory limits, or some reported file parsing bug i found online. 
        while True:
            try:
                tls_ctx = None
                if self.ca_cert:
                    tls_ctx = ssl.create_default_context(cafile=self.ca_cert)
                    # Load client certificate for mutual TLS (mTLS)
                    if self.client_cert and self.client_key:
                        tls_ctx.load_cert_chain(
                            certfile=self.client_cert,
                            keyfile=self.client_key,
                        )
                    # tls_ctx.check_hostname = False  #if it doesnt work then there is a hostname mismatch between the cert and the broker address, which is expected since we use a self-signed cert. This disables that check, but it would be better to generate the cert with the correct hostname or use a SAN.
                async with aiomqtt.Client(
                    hostname=self.host,
                    port=self.port,
                    tls_context=tls_ctx,
                    username=self.username,
                    password=self.password,
                    will=self.will,
                ) as c:
                    log.info(
                        "broker connected %s:%d tls=%s mtls=%s",
                        self.host, self.port,
                        tls_ctx is not None,
                        self.client_cert is not None,
                    )
                    try:
                        async with asyncio.TaskGroup() as tg:
                            tg.create_task(self.publish_loop(c))
                            tg.create_task(self.subscribe_loop(c))
                    except* aiomqtt.MqttError as eg:
                        log.warning("MQTT %s:%d session error: %s", self.host, self.port, eg)
            except Exception as err:
                log.warning("MQTT %s:%d reconnect in 5s: %s", self.host, self.port, err)
                await asyncio.sleep(5)

