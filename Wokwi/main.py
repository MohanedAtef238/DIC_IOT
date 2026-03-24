import network
import time
import ujson
import ntptime
from machine import Pin, ADC, PWM
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

TOPIC_TELEMETRY = b"campus/b01/floor1/room001/telemetry"
TOPIC_HEARTBEAT = b"campus/heartbeat/room001"

TOPIC_HVAC = b"campus/b01/floor1/room001/hvac"
TOPIC_DIMMER = b"campus/b01/floor1/room001/dimmer"

UTC_OFFSET = 2 * 3600  

# =========================
# SENSORS
# =========================
dht_sensor = dht.DHT22(Pin(4))
pir = Pin(5, Pin.IN)

ldr = ADC(Pin(34))
ldr.atten(ADC.ATTN_11DB)

# =========================
# ACTUATORS
# =========================
led = PWM(Pin(18), freq=1000)

hvac_mode = "eco"
lighting_dimmer = 50

# =========================
# WIFI
# =========================
def connect_wifi():
    wifi = network.WLAN(network.STA_IF)
    wifi.active(True)
    wifi.connect(SSID, PASSWORD)

    while not wifi.isconnected():
        time.sleep(0.5)

    print("WiFi Connected!")

# =========================
# TIME
# =========================
def sync_time():
    try:
        ntptime.settime()
        print("Time synced!")
    except:
        print("NTP failed")

def get_timestamp():
    return int(time.time() + UTC_OFFSET)

# =========================
# MQTT CALLBACK
# =========================
def mqtt_callback(topic, msg):
    global hvac_mode, lighting_dimmer

    try:
        msg = msg.decode()

        # Try parsing JSON
        try:
            data = ujson.loads(msg)
        except:
            data = msg  # fallback if plain string

        if topic == TOPIC_HVAC:
            if isinstance(data, dict):
                hvac_mode = data.get("hvac_mode", "eco").upper()
            else:
                hvac_mode = data.upper()

            # enforce allowed modes
            if hvac_mode not in ["ON", "OFF", "ECO"]:
                hvac_mode = "ECO"

            print("HVAC set to:", hvac_mode)

        elif topic == TOPIC_DIMMER:
            if isinstance(data, dict):
                lighting_dimmer = int(data.get("lighting_dimmer", 50))
            else:
                lighting_dimmer = int(data)

            lighting_dimmer = max(0, min(100, lighting_dimmer))

            duty = int((lighting_dimmer / 100) * 1023)
            led.duty(duty)

            print("Dimmer set to:", lighting_dimmer)

    except Exception as e:
        print("MQTT error:", e)

# =========================
# MQTT
# =========================
client = None

def connect_mqtt():
    global client

    client = MQTTClient(
        CLIENT_ID,
        MQTT_BROKER,
        port=MQTT_PORT,
        user=MQTT_USER,
        password=MQTT_PASS,
        ssl=True,
        ssl_params={"server_hostname": MQTT_BROKER}
    )

    client.set_callback(mqtt_callback)
    client.connect()

    # Subscribe to control topics
    client.subscribe(TOPIC_HVAC)
    client.subscribe(TOPIC_DIMMER)

    print("MQTT Connected & Subscribed!")

def publish(topic, msg):
    try:
        client.publish(topic, msg)
    except:
        print("Reconnect MQTT...")
        connect_mqtt()

# =========================
# MAIN
# =========================
connect_wifi()
sync_time()
connect_mqtt()

last_publish = 0

while True:
    try:
        client.check_msg()  # check incoming MQTT messages

        # Read sensors
        dht_sensor.measure()
        temp = dht_sensor.temperature()
        hum = dht_sensor.humidity()

        occupancy = bool(pir.value())

        raw_light = ldr.read()
        light_level = int((raw_light / 4095) * 1000)

     
        payload = {
            "metadata": {
                "sensor_id": "b01-f01-r001",
                "building": "b01",
                "floor": 1,
                "room": 1,
                "timestamp": get_timestamp()
            },
            "sensors": {
                "temperature": temp,
                "humidity": hum,
                "occupancy": occupancy,
                "light_level": light_level
            },
            "actuators": {
                "hvac_mode": hvac_mode,
                "lighting_dimmer": lighting_dimmer
            }
        }

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