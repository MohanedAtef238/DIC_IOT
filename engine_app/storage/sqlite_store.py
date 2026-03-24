import sqlite3

TABLE_NAME = "room_payloads"
EXPECTED_COLUMNS = [
    "room_id",
    "last_temp",
    "last_humidity",
    "hvac_mode",
    "target_temp",
    "last_update",
]


class SQLiteRoomStore:
    def __init__(self, db_path):
        self.db_path = db_path
        self._conn = None

    def connect(self):
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._ensure_schema()

    def _ensure_schema(self):
        existing_columns = self._fetchall(f"PRAGMA table_info({TABLE_NAME})")

        if existing_columns:
            current_column_names = [column[1] for column in existing_columns]
            if current_column_names != EXPECTED_COLUMNS:
                self._execute(f"DROP TABLE {TABLE_NAME}")

        self._execute(
            """
            CREATE TABLE IF NOT EXISTS room_payloads (
                room_id TEXT PRIMARY KEY,
                last_temp REAL NOT NULL,
                last_humidity REAL NOT NULL,
                hvac_mode TEXT NOT NULL,
                target_temp REAL NOT NULL,
                last_update INTEGER NOT NULL
            )
            """
        )

    def close(self):
        if self._conn is None:
            return

        self._conn.close()
        self._conn = None

    def load_room_states(self):
        rows = self._fetchall(
            """
            SELECT room_id, last_temp, last_humidity, hvac_mode, target_temp, last_update
            FROM room_payloads
            """
        )
        return {
            row[0]: {
                "last_temp": row[1],
                "last_humidity": row[2],
                "hvac_mode": row[3],
                "target_temp": row[4],
                "last_update": row[5],
            }
            for row in rows
        }

    def save_room_payload(self, payload):
        self._execute(
            """
            INSERT INTO room_payloads (
                room_id, last_temp, last_humidity, hvac_mode, target_temp, last_update
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(room_id) DO UPDATE SET
                last_temp = excluded.last_temp,
                last_humidity = excluded.last_humidity,
                hvac_mode = excluded.hvac_mode,
                target_temp = excluded.target_temp,
                last_update = excluded.last_update
            """,
            (
                payload["room_id"],
                payload["temperature"],
                payload["humidity"],
                payload["hvac_status"],
                payload["target_temp"],
                payload["ts"],
            ),
        )

    def _execute(self, query, params=()):
        cursor = self._conn.cursor()
        cursor.execute(query, params)
        self._conn.commit()

    def _fetchall(self, query, params=()):
        cursor = self._conn.cursor()
        cursor.execute(query, params)
        return cursor.fetchall()
