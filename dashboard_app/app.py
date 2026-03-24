import os
import sqlite3
from datetime import datetime, timezone

import streamlit as st

DB_PATH = os.environ.get("SQLITE_DB_PATH", "/data/campus.db")

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
