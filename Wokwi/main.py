import network
import time
import ujson
import ntptime
import ussl
from machine import Pin, ADC
import dht
from umqtt.simple import MQTTClient

# =========================
# CONFIG
# =========================
SSID = "Wokwi-GUEST"
PASSWORD = ""

MQTT_BROKER = "9ee5ca1bdb284fceaf7e3efd2799e852.s1.eu.hivemq.cloud"
MQTT_PORT = 8883

CLIENT_ID = "202200059-device"

MQTT_USER = "Kareem"
MQTT_PASS = "Kareem123456"

TOPIC_TELEMETRY = b"campus/bldg_01/floor_01/room_001/telemetry"
TOPIC_HEARTBEAT = b"campus/heartbeat/room_001"

UTC_OFFSET = 2 * 3600  

# =========================
# SENSORS
# =========================
dht_sensor = dht.DHT22(Pin(4))
pir = Pin(5, Pin.IN)

ldr = ADC(Pin(34))
ldr.atten(ADC.ATTN_11DB)

# =========================
# WIFI
# =========================
def connect_wifi():
    wifi = network.WLAN(network.STA_IF)
    wifi.active(True)
    wifi.connect(SSID, PASSWORD)

    print("Connecting WiFi...")
    while not wifi.isconnected():
        time.sleep(0.5)

    print("WiFi Connected!")

# =========================
# TIME (RETRY SAFE)
# =========================
def sync_time():
    for _ in range(5):
        try:
            ntptime.settime()
            print("NTP Synced!")
            return
        except:
            print("Retrying NTP...")
            time.sleep(1)
    print("NTP FAILED")

def get_timestamp():
    return int(time.time() + UTC_OFFSET)

def get_readable_time():
    t = time.localtime(time.time() + UTC_OFFSET)
    return "{:02d}:{:02d}:{:02d}".format(t[3], t[4], t[5])

# =========================
# MQTT (SSL + RECONNECT)
# =========================
client = None

def connect_mqtt():
    global client
    while True:
        try:
            client = MQTTClient(
                CLIENT_ID,
                MQTT_BROKER,
                port=MQTT_PORT,
                user=MQTT_USER,
                password=MQTT_PASS,
                ssl=True,
                ssl_params={"server_hostname": MQTT_BROKER}
            )
            client.connect()
            print("MQTT Connected (Cloud)!")
            return
        except Exception as e:
            print("MQTT connect failed:", e)
            time.sleep(3)

def publish(topic, msg):
    global client
    try:
        client.publish(topic, msg)
    except:
        print("MQTT lost... reconnecting")
        connect_mqtt()
        client.publish(topic, msg)

# =========================
# JSON VALIDATION
# =========================
def validate_payload(payload):
    try:
        assert isinstance(payload["sensor_id"], str)
        assert 15 <= payload["temperature"] <= 50
        assert 0 <= payload["humidity"] <= 100
        assert isinstance(payload["occupancy"], bool)
        assert 0 <= payload["light_level"] <= 1000
        assert payload["hvac_mode"] in ["ON", "OFF", "ECO"]
        return True
    except Exception as e:
        print("Invalid payload:", e)
        return False

# =========================
# MAIN
# =========================
connect_wifi()
sync_time()
connect_mqtt()

last_publish = 0

while True:
    try:
        # Read sensors
        dht_sensor.measure()
        temp = dht_sensor.temperature()
        hum = dht_sensor.humidity()

        occupancy = bool(pir.value())

        raw_light = ldr.read()
        light_level = int((raw_light / 4095) * 1000)

        if occupancy and light_level < 300:
            light_level = 500

        payload = {
            "sensor_id": "b01-f01-r001",
            "timestamp": get_timestamp(),
            "readable_time": get_readable_time(),
            "temperature": temp,
            "humidity": hum,
            "occupancy": occupancy,
            "light_level": light_level,
            "hvac_mode": "OFF",
            "lighting_dimmer": int(light_level / 10)
        }

        if not validate_payload(payload):
            continue

        if time.time() - last_publish >= 5:

            publish(TOPIC_TELEMETRY, ujson.dumps(payload))

            publish(TOPIC_HEARTBEAT, ujson.dumps({
                "status": "alive",
                "timestamp": get_timestamp()
            }))

            print("Published:", payload)

            last_publish = time.time()

        time.sleep(1)

    except Exception as e:
        print("Error:", e)
        time.sleep(2)