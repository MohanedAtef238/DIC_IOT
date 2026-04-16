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
rm -f mosquitto.csr

# DTLS pre-shared key 
PSK_B64=$(openssl rand -hex 16 | python3 -c \
    "import sys,base64; print(base64.b64encode(bytes.fromhex(sys.stdin.read().strip())).decode())")
cat > dtls_psk.json <<EOF
{
    "psk_identity": "campus-iot-sensor",
    "psk_key_b64": "$PSK_B64"
}
EOF

# Client Certificates
generate_client_cert() {
    local COMMON_NAME=$1
    echo "Generating client cert for $COMMON_NAME..."
    openssl genrsa -out ${COMMON_NAME}.key 2048 2>/dev/null
    openssl req -new -key ${COMMON_NAME}.key -subj "/CN=${COMMON_NAME}/O=DIC_IOT/C=EG" -out ${COMMON_NAME}.csr 2>/dev/null
    openssl x509 -req -in ${COMMON_NAME}.csr -CA ca.crt -CAkey ca.key -CAcreateserial -days $DAYS -sha256 -out ${COMMON_NAME}.crt 2>/dev/null
    rm -f ${COMMON_NAME}.csr
}

# Engine client cert — super-user, full campus/# access via ACL
generate_client_cert "engine"

# Per-floor client certs — CN matches floor number for pattern ACL
for floor in 01 02 03 04 05 06 07 08 09 10; do
    generate_client_cert "$floor"
done

# Clean up serial file after all certs are generated
rm -f ca.srl

# MQTT broker password file for the 'engine' service account
MQTT_PASS=$(openssl rand -base64 18 | tr -d '/+=')
docker run --rm \
    -v "$(cd .. && pwd)/mosquitto/config:/mosquitto/config" \
    eclipse-mosquitto:2 \
    sh -c "mosquitto_passwd -b -c /mosquitto/config/passwd engine '$MQTT_PASS'"

echo ""
echo "=== Generated certificates ==="
ls -lh ca.crt ca.key mosquitto.crt mosquitto.key engine.crt engine.key dtls_psk.json
for floor in 01 02 03 04 05 06 07 08 09 10; do
    ls -lh ${floor}.crt ${floor}.key
done

echo ""
echo "--- Copy these into .env ---"
echo "DTLS_PSK_IDENTITY=campus-iot-sensor"
echo "DTLS_PSK_KEY_B64=$PSK_B64"
echo "MQTT_USER=engine"
echo "MQTT_PASS=$MQTT_PASS"
echo ""
echo "# Client cert paths (inside container, mounted via docker-compose)"
echo "MQTT_CLIENT_CERT=/certs/engine.crt"
echo "MQTT_CLIENT_KEY=/certs/engine.key"
