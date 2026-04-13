#!/usr/bin/env bash
# Run once from repo root: bash certs/generate_certs.sh
set -euo pipefail
cd "$(dirname "$0")"

DAYS=3650
SAN="subjectAltName=DNS:mosquitto,DNS:localhost,IP:127.0.0.1"

# CA
openssl genrsa -out ca.key 4096
openssl req -x509 -new -nodes -key ca.key -sha256 -days $DAYS \
    -subj "/CN=CampusIoT-CA/O=DIC_IOT/C=EG" -out ca.crt

# Broker cert signed by CA (SAN covers both docker hostname and localhost)
openssl genrsa -out mosquitto.key 2048
openssl req -new -key mosquitto.key \
    -subj "/CN=mosquitto/O=DIC_IOT/C=EG" -out mosquitto.csr
openssl x509 -req -in mosquitto.csr \
    -CA ca.crt -CAkey ca.key -CAcreateserial \
    -days $DAYS -sha256 -extfile <(printf "$SAN") \
    -out mosquitto.crt
rm -f mosquitto.csr ca.srl

# DTLS pre-shared key
PSK_B16=$(openssl rand -hex 16 | python3 -c \
    "import sys,base64; print(base64.b64encode(bytes.fromhex(sys.stdin.read().strip())).decode())")
cat > dtls_psk.json <<EOF
{
    "psk_identity": "campus-iot-sensor",
    "psk_key_b64": "$PSK_B16"
}
EOF

ls -lh ca.crt ca.key mosquitto.crt mosquitto.key dtls_psk.json

echo "debugging purposes.."
echo "DTLS_PSK_IDENTITY=campus-iot-sensor"
echo "DTLS_PSK_KEY_B64=$PSK_B16"
