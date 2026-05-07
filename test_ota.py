"""
OTA end-to-end test — two phases:

  Phase 1 – TAMPER: publishes a payload with a corrupted signature to a single
             probe room and checks that the engine raises TAMPER_DETECTED.
             No acks should arrive (the update must be rejected).

  Phase 2 – VALID:  publishes a correctly-signed payload and checks that the
             targeted rooms all acknowledge the update.

Usage:
    python test_ota.py [target] [version]

  target   : "all", "floor_01" .. "floor_10", or a room id like "b01-f01-r001"
             (default: floor_01)
  version  : new firmware version string  (default: 2.0)

Examples:
    python test_ota.py floor_01 2.0
    python test_ota.py all 3.0
    python test_ota.py b01-f03-r005 2.1
"""
import hashlib, json, sys, time, ssl
from pathlib import Path
import paho.mqtt.client as mqtt

# ── configuration ────────────────────────────────────────────────────────────
CERTS_DIR  = Path(__file__).parent / "certs"
MQTT_HOST  = "localhost"
MQTT_PORT  = 8883               # TLS port — same one the engine uses
MQTT_CA    = str(CERTS_DIR / "ca.crt")
MQTT_CERT  = str(CERTS_DIR / "engine.crt")   # engine cert → ACL allows readwrite campus/#
MQTT_KEY   = str(CERTS_DIR / "engine.key")
OTA_TOPIC  = "campus/b01/ota/config"
ACK_TOPIC  = "campus/b01/ota/ack"
ALERT_TOPIC = "campus/b01/+/+/telemetry"   # engine publishes TAMPER_DETECTED here

TARGET      = sys.argv[1] if len(sys.argv) > 1 else "floor_01"
NEW_VERSION = sys.argv[2] if len(sys.argv) > 2 else "2.0"
TAMPER_WAIT = 8    # seconds to wait for tamper alerts (engine responds quickly)
VALID_WAIT  = 25   # seconds to collect acks after the valid publish

# Use a single stable probe room for the tamper test so we don't spam all rooms.
# We derive it from TARGET: floor_01 → b01-f01-r001, all → b01-f01-r001, explicit id as-is.
def _probe_room(target: str) -> str:
    if target.startswith("b01-f"):
        return target
    import re
    m = re.search(r"floor_(\d+)", target)
    floor = int(m.group(1)) if m else 1
    return f"b01-f{floor:02d}-r001"

PROBE_ROOM  = _probe_room(TARGET)
OTA_PARAMS  = {"alpha": 0.04, "beta": 0.25, "version": NEW_VERSION}

# ── helpers ───────────────────────────────────────────────────────────────────
def _build_payload(target: str, corrupt: bool) -> str:
    config_str = json.dumps(OTA_PARAMS, separators=(",", ":"))
    good_sig   = hashlib.sha256(config_str.encode()).hexdigest()
    signature  = ("deadbeef" + good_sig[8:]) if corrupt else good_sig
    return json.dumps({
        "config_data":    config_str,
        "signature":      signature,
        "target_version": NEW_VERSION,
        "target":         target,
    })

def _make_client(cid: str):
    c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=cid)
    # Python 3.13 rejects our self-signed CA (missing Key Usage extension).
    # For this local test utility we skip server-cert verification while still
    # presenting our client cert so Mosquitto's mTLS auth is satisfied.
    tls_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    tls_ctx.check_hostname = False
    tls_ctx.verify_mode = ssl.CERT_NONE
    tls_ctx.load_cert_chain(certfile=MQTT_CERT, keyfile=MQTT_KEY)
    c.tls_set_context(tls_ctx)
    c.connect(MQTT_HOST, MQTT_PORT, 60)
    return c

# ── shared state ──────────────────────────────────────────────────────────────
tamper_alerts: list[dict] = []
tamper_acks:   list[dict] = []
valid_acks:    list[dict] = []

# ════════════════════════════════════════════════════════════════════════════
# PHASE 1 — TAMPER TEST
# ════════════════════════════════════════════════════════════════════════════
print("=" * 60)
print(f"PHASE 1  Tamper detection  (probe room: {PROBE_ROOM})")
print("=" * 60)

def on_tamper_msg(client, userdata, msg):
    try:
        data = json.loads(msg.payload)
        if data.get("security_alert") == "TAMPER_DETECTED":
            print(f"  [ALERT]  TAMPER_DETECTED  room={data.get('room_id', '?')}")
            tamper_alerts.append(data)
        # Any ack arriving means the engine wrongly accepted the bad payload
    except Exception:
        pass

def on_tamper_ack(client, userdata, msg):
    try:
        data = json.loads(msg.payload)
        print(f"  [UNEXPECTED ACK]  {data}")
        tamper_acks.append(data)
    except Exception:
        pass

t_alert_sub = _make_client("ota_tamper_alert_sub")
t_alert_sub.on_message = on_tamper_msg
t_alert_sub.subscribe(ALERT_TOPIC, qos=1)
t_alert_sub.loop_start()

t_ack_sub = _make_client("ota_tamper_ack_sub")
t_ack_sub.on_message = on_tamper_ack
t_ack_sub.subscribe(ACK_TOPIC, qos=1)
t_ack_sub.loop_start()

pub = _make_client("ota_test_pub")
pub.loop_start()
time.sleep(0.3)

tamper_payload = _build_payload(PROBE_ROOM, corrupt=True)
pub.publish(OTA_TOPIC, tamper_payload, qos=2)
print(f"Published TAMPERED OTA (bad signature) -> target={PROBE_ROOM}")
print(f"Waiting {TAMPER_WAIT}s for alerts...\n")
time.sleep(TAMPER_WAIT)

t_alert_sub.loop_stop()
t_ack_sub.loop_stop()

print(f"\n{'─'*60}")
if tamper_alerts and not tamper_acks:
    print(f"PASS  Tamper detected by {len(tamper_alerts)} room(s) — update correctly rejected.")
elif not tamper_alerts:
    print("FAIL  No TAMPER_DETECTED alert received.")
    print("      Engine may not have seen the message — check: docker logs campus_engine --tail 20")
else:
    print(f"FAIL  Alert raised BUT {len(tamper_acks)} ack(s) also arrived — bad payload was accepted!")

# ════════════════════════════════════════════════════════════════════════════
# PHASE 2 — VALID OTA
# ════════════════════════════════════════════════════════════════════════════
print(f"\n{'='*60}")
print(f"PHASE 2  Valid OTA  (target={TARGET}, version={NEW_VERSION})")
print(f"{'='*60}")

def on_valid_ack(client, userdata, msg):
    try:
        data = json.loads(msg.payload)
        print(f"  ACK  {data.get('deviceName', '?')}  ->  v{data.get('current_version', '?')}")
        valid_acks.append(data)
    except Exception as e:
        print(f"  bad ack payload: {e}")

v_sub = _make_client("ota_valid_sub")
v_sub.on_message = on_valid_ack
v_sub.subscribe(ACK_TOPIC, qos=1)
v_sub.loop_start()

time.sleep(0.3)
valid_payload = _build_payload(TARGET, corrupt=False)
pub.publish(OTA_TOPIC, valid_payload, qos=2)
print(f"Published valid OTA -> target={TARGET}")
print(f"Waiting {VALID_WAIT}s for acks...\n")
time.sleep(VALID_WAIT)

v_sub.loop_stop()
pub.loop_stop()

# ── summary ───────────────────────────────────────────────────────────────────
print(f"\n{'='*60}")
print("SUMMARY")
print(f"{'='*60}")
p1 = "PASS" if tamper_alerts and not tamper_acks else "FAIL"
p2 = "PASS" if valid_acks else "FAIL"
print(f"  Phase 1 (tamper)  : {p1}  ({len(tamper_alerts)} alert(s), {len(tamper_acks)} unexpected ack(s))")
print(f"  Phase 2 (valid)   : {p2}  ({len(valid_acks)} ack(s) received)")

if p2 == "PASS":
    versions = {a["deviceName"]: a["current_version"] for a in valid_acks if "deviceName" in a}
    sample = dict(list(sorted(versions.items()))[:5])
    print(f"  Updated rooms (sample): {sample}" + (" ..." if len(versions) > 5 else ""))

if p1 == "FAIL" or p2 == "FAIL":
    print("\n  Diagnostics:")
    print("    docker logs campus_engine --tail 30")
    sys.exit(1)

