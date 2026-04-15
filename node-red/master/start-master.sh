#!/bin/sh
set -eu

node /usr/src/node-red/bootstrap-floors.js
node /usr/src/node-red/watch-flows.js &

exec npm start -- --userDir /data
