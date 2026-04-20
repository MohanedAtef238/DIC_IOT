FROM nodered/node-red:latest

USER root
WORKDIR /usr/src/node-red

# Pre-install specific nodes requested (CoAP)
RUN npm install --no-update-notifier --no-fund --omit=dev node-red-contrib-coap@0.8.0

COPY node-red/master/start-worker.sh /usr/src/node-red/start-worker.sh
COPY node-red/master/watch-flows.js /usr/src/node-red/watch-flows.js

RUN chmod +x /usr/src/node-red/start-worker.sh

# Standard Node-RED startup with watch-flows enabled
ENTRYPOINT ["/usr/src/node-red/start-worker.sh"]
