#!/bin/sh
set -eu

stop_floors() {
    echo "[master] Received termination signal. Stopping Node-RED workers..."
    node /usr/src/node-red/bootstrap-floors.js stop || true
    
    echo "[master] Stopping Node-RED master..."
    kill -TERM "$NODE_PID" 2>/dev/null || true
    wait "$NODE_PID" || true
    exit 0
}

trap stop_floors TERM INT

node /usr/src/node-red/bootstrap-floors.js
node /usr/src/node-red/watch-flows.js &

npm start -- --userDir /data &
NODE_PID=$!

wait "$NODE_PID"
