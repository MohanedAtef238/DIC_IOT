#!/bin/sh
set -eu

# FLOW_FILE is now mandatory. Fail fast if not provided.
if [ -z "${FLOW_FILE:-}" ]; then
  echo "ERROR: FLOW_FILE environment variable must be set."
  exit 1
fi
FLOW_NAME="$FLOW_FILE"

# Start the watch script in the background
node /usr/src/node-red/watch-flows.js &

# Start Node-RED with the specific flow file
# We use node directly to ensure arguments are passed cleanly
exec node node_modules/node-red/red.js --userDir /data --flows "$FLOW_NAME"
