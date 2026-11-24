"""Live status of the room simulator, read from inside the campus_engine container.

Run:  docker exec -i campus_engine python - < docs/evidence/simulator_status_check.py
Reads only: the simulator's SQLite state and the container's open network sockets.
"""
import collections
import datetime
import sqlite3
import time

now = int(time.time())
print("container clock (UTC):", datetime.datetime.fromtimestamp(now, datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S"))
print("simulator process (PID 1):", open("/proc/1/cmdline").read().replace("\0", " ").strip())
print()

rows = sqlite3.connect("/data/campus.db").execute(
    "SELECT room_id, last_update, hvac_mode FROM room_payloads").fetchall()
print("rooms in the simulator database:", len(rows))
print("rooms whose state was written in the last 60 s:", sum(1 for r in rows if now - r[1] <= 60))
per_floor = collections.Counter(r[0].split("-")[1] for r in rows)
print("rooms per floor:", " ".join(f"{k}={v}" for k, v in sorted(per_floor.items())))
print("HVAC modes:", dict(collections.Counter(r[2] for r in rows)))
print()


def sockets(*paths):
    out = []
    for path in paths:
        try:
            lines = open(path).read().splitlines()[1:]
        except FileNotFoundError:
            continue
        for line in lines:
            f = line.split()
            out.append((int(f[1].rsplit(":", 1)[1], 16), int(f[2].rsplit(":", 1)[1], 16), f[3]))
    return out


coap = [s for s in sockets("/proc/1/net/udp", "/proc/1/net/udp6") if 5700 <= s[0] <= 5899]
print("CoAP room servers: UDP sockets listening on ports 5700-5899:", len(coap),
      "on", len({s[0] for s in coap}), "distinct ports (one port per CoAP room)")
mqtt = [s for s in sockets("/proc/1/net/tcp", "/proc/1/net/tcp6") if s[2] == "01" and s[1] == 8883]
print("MQTT clients: established TLS connections to the broker on port 8883:", len(mqtt))
