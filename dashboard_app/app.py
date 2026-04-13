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

DB_PATH = os.environ.get("SQLITE_DB_PATH", "/data/campus.db")
MQTT_HOST = os.environ.get("MQTT_HOST", "mosquitto")
MQTT_PORT = int(os.environ.get("MQTT_PORT", "1883"))
FLEET_HVAC_TOPIC = "campus/b01/actuator/hvac"
VALID_HVAC_MODES = ["OFF", "ECO", "ON"]

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", stream=sys.stdout)
log = logging.getLogger("dashboard")


class DashboardMQTTRuntime:
    def __init__(self, host, port):
        self._broker = MQTTClient(host, port)
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
    runtime = DashboardMQTTRuntime(MQTT_HOST, MQTT_PORT)
    atexit.register(runtime.close)
    return runtime


def publish_fleet_hvac(mode):
    runtime = get_mqtt_runtime()
    runtime.publish_json(
        FLEET_HVAC_TOPIC,
        {"hvac_mode": mode, "command_id": str(uuid.uuid4())},
    )


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
            SELECT room_id, last_temp, last_humidity, hvac_mode, target_temp, last_update
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
