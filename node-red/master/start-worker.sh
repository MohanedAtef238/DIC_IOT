#!/bin/sh
set -eu

# Ensure workers start with both flows and credentials from the shared source.
FLOW_SOURCE_PATH="${FLOW_SOURCE:-/data/flows.json}"
FLOW_TARGET_PATH="${FLOW_TARGET:-/data/flows.json}"
FLOW_CRED_SOURCE_PATH="${FLOW_CRED_SOURCE:-${FLOW_SOURCE_PATH%flows.json}flows_cred.json}"
FLOW_CRED_TARGET_PATH="${FLOW_CRED_TARGET:-${FLOW_TARGET_PATH%flows.json}flows_cred.json}"

mkdir -p "$(dirname "$FLOW_TARGET_PATH")"

if [ -f "$FLOW_SOURCE_PATH" ]; then
	cp "$FLOW_SOURCE_PATH" "$FLOW_TARGET_PATH"
fi

if [ -f "$FLOW_CRED_SOURCE_PATH" ]; then
	cp "$FLOW_CRED_SOURCE_PATH" "$FLOW_CRED_TARGET_PATH"
fi


node /usr/src/node-red/watch-flows.js &

exec npm start -- --userDir /data
