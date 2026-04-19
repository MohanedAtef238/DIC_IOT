import atexit
import os
import sqlite3
import logging
import sys
import threading
import asyncio
import uuid
from datetime import datetime, timezone

import streamlit as st

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
ENGINE_APP_PATH = os.path.join(PROJECT_ROOT, "engine_app")
if ENGINE_APP_PATH not in sys.path:
    sys.path.insert(0, ENGINE_APP_PATH)

from network.mqtt_client import MQTTClient
from network.topics import (
    room_base_topic,
    room_hvac_command_topic,
    room_light_dimmer_command_topic,
)

DB_PATH = os.environ.get("SQLITE_DB_PATH", "/data/campus.db")
MQTT_HOST = os.environ.get("MQTT_HOST", "mosquitto")
MQTT_PORT = int(os.environ.get("MQTT_PORT", "8883"))
MQTT_CA_CERT = os.environ.get("MQTT_CA_CERT")
MQTT_CLIENT_CERT = os.environ.get("MQTT_CLIENT_CERT")
MQTT_CLIENT_KEY = os.environ.get("MQTT_CLIENT_KEY")
FLEET_HVAC_TOPIC = "campus/b01/actuator/hvac"
VALID_HVAC_MODES = ["OFF", "ECO", "ON"]

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", stream=sys.stdout)
log = logging.getLogger("dashboard")


class DashboardMQTTRuntime:
    def __init__(self, host, port, ca_cert=None, client_cert=None, client_key=None):
        self._broker = MQTTClient(
            host, port, ca_cert=ca_cert, client_cert=client_cert, client_key=client_key
        )
        self._loop = asyncio.new_event_loop()
        self._ready = threading.Event()
        self._thread = threading.Thread(target=self._thread_main, daemon=True)
        self._thread.start()
        if not self._ready.wait(timeout=5):
            raise RuntimeError("mqtt runtime thread did not start")

    def _thread_main(self):
        asyncio.set_event_loop(self._loop)
        self._loop.create_task(self._broker.run())
        self._ready.set()
        self._loop.run_forever()

    def publish_json(self, topic, payload):
        fut = asyncio.run_coroutine_threadsafe(self._broker.publish_json(topic, payload), self._loop)
        fut.result(timeout=5)

    def close(self):
        if self._loop.is_running():
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread.is_alive():
            self._thread.join(timeout=2)


@st.cache_resource
def get_mqtt_runtime():
    runtime = DashboardMQTTRuntime(
        MQTT_HOST,
        MQTT_PORT,
        ca_cert=MQTT_CA_CERT,
        client_cert=MQTT_CLIENT_CERT,
        client_key=MQTT_CLIENT_KEY,
    )
    atexit.register(runtime.close)
    return runtime


def publish_fleet_hvac(mode):
    runtime = get_mqtt_runtime()
    runtime.publish_json(
        FLEET_HVAC_TOPIC,
        {"hvac_mode": mode, "command_id": str(uuid.uuid4())},
    )


def format_room_id(floor, room_num):
    return f"b01-f{floor:02d}-r{room_num:03d}"


def publish_room_hvac(floor, room_num, mode):
    runtime = get_mqtt_runtime()
    topic = room_hvac_command_topic(room_base_topic(floor, room_num))
    runtime.publish_json(
        topic,
        {
            "room_id": format_room_id(floor, room_num),
            "hvac_mode": mode,
            "command_id": str(uuid.uuid4()),
        },
    )
    return topic


def publish_room_light_dimmer(floor, room_num, dimmer):
    runtime = get_mqtt_runtime()
    topic = room_light_dimmer_command_topic(room_base_topic(floor, room_num))
    runtime.publish_json(
        topic,
        {
            "room_id": format_room_id(floor, room_num),
            "lighting_dimmer": dimmer,
            "command_id": str(uuid.uuid4()),
        },
    )
    return topic


def parse_room_id(room_id):
    try:
        _, floor_segment, room_segment = room_id.split("-")
        floor = int(floor_segment.lstrip("f"))
        room_num = int(room_segment.lstrip("r"))
        return floor, room_num
    except Exception:
        return None, None


st.set_page_config(page_title="Campus IoT Dashboard", layout="wide")
st.title("Campus IoT Dashboard")
st.caption(f"SQLite source: {DB_PATH}")


def load_rows(db_path):
    if not os.path.exists(db_path):
        return []

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT room_id, last_temp, last_humidity, hvac_mode, target_temp, lighting_dimmer, last_update
            FROM room_payloads
            ORDER BY room_id
            """
        ).fetchall()
    finally:
        conn.close()

    result = []
    for row in rows:
        last_update = datetime.fromtimestamp(row["last_update"], tz=timezone.utc).isoformat()
        result.append(
            {
                "room_id": row["room_id"],
                "last_temp": row["last_temp"],
                "last_humidity": row["last_humidity"],
                "hvac_mode": row["hvac_mode"],
                "target_temp": row["target_temp"],
                "lighting_dimmer": row["lighting_dimmer"],
                "last_update_utc": last_update,
            }
        )
    return result


st.subheader("Fleet HVAC Control")
control_col1, control_col2 = st.columns([2, 1])
selected_mode = control_col1.selectbox("HVAC mode for all rooms", VALID_HVAC_MODES, index=0)
if control_col2.button("Apply to fleet", use_container_width=True):
    try:
        publish_fleet_hvac(selected_mode)
        st.success(f"Fleet HVAC command sent: {selected_mode}")
        log.info("fleet hvac command sent: %s", selected_mode)
    except Exception as exc:
        st.error(f"Failed to publish fleet command: {exc}")

rows = load_rows(DB_PATH)

if not rows:
    st.warning("No room data found yet. Start the engine and wait for a publish cycle.")
    st.stop()

room_options = []
for row in rows:
    floor, room_num = parse_room_id(row["room_id"])
    if floor is not None and room_num is not None:
        room_options.append((floor, room_num))
room_options = sorted(set(room_options))
selected_room = room_options[0] if room_options else (1, 1)

with st.expander("Targeted room control"):
    selection_col1, selection_col2 = st.columns([2, 3])
    selected_room = selection_col1.selectbox(
        "Select room to target",
        room_options,
        format_func=lambda r: f"Floor {r[0]:02d} / Room {r[1]:03d}",
    )

    room_floor, room_num = selected_room
    target_mode = selection_col2.selectbox("HVAC mode for selected room", VALID_HVAC_MODES, index=0)
    target_dimmer = selection_col2.slider("Lighting dimmer %", min_value=0, max_value=100, value=75)

    target_hvac_col, target_dimmer_col = st.columns([2, 2])
    if target_hvac_col.button("Apply HVAC to selected room", use_container_width=True):
        try:
            topic = publish_room_hvac(room_floor, room_num, target_mode)
            st.success(f"Room HVAC command sent to {topic}: {target_mode}")
            log.info("room hvac command sent to %s: %s", topic, target_mode)
        except Exception as exc:
            st.error(f"Failed to publish room HVAC command: {exc}")

    if target_dimmer_col.button("Apply dimmer to selected room", use_container_width=True):
        try:
            topic = publish_room_light_dimmer(room_floor, room_num, target_dimmer)
            st.success(f"Room light dimmer command sent to {topic}: {target_dimmer}%")
            log.info("room dimmer command sent to %s: %s", topic, target_dimmer)
        except Exception as exc:
            st.error(f"Failed to publish room dimmer command: {exc}")

hvac_modes = sorted({row["hvac_mode"] for row in rows})
selected_modes = st.multiselect("Filter HVAC mode", hvac_modes, default=hvac_modes)
search = st.text_input("Filter room id contains", "")

filtered = [
    row
    for row in rows
    if row["hvac_mode"] in selected_modes and search.lower() in row["room_id"].lower()
]

col1, col2, col3 = st.columns(3)
col1.metric("Rooms", len(filtered))
col2.metric("Avg Temp", round(sum(r["last_temp"] for r in filtered) / len(filtered), 2) if filtered else "-")
col3.metric("Avg Humidity", round(sum(r["last_humidity"] for r in filtered) / len(filtered), 2) if filtered else "-")

st.dataframe(filtered, use_container_width=True, hide_index=True)

st.caption("Tip: press R in the browser to refresh, or enable auto-refresh in Streamlit settings.")
