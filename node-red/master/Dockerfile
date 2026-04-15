FROM nodered/node-red:latest

USER root
WORKDIR /usr/src/node-red

RUN npm install --no-update-notifier --no-fund --omit=dev dockerode node-red-contrib-coap@0.8.0

COPY node-red/master/bootstrap-floors.js /usr/src/node-red/bootstrap-floors.js
COPY node-red/master/start-master.sh /usr/src/node-red/start-master.sh
COPY node-red/master/start-worker.sh /usr/src/node-red/start-worker.sh
COPY node-red/master/watch-flows.js /usr/src/node-red/watch-flows.js

RUN chmod +x /usr/src/node-red/start-master.sh /usr/src/node-red/start-worker.sh

ENTRYPOINT ["/usr/src/node-red/start-worker.sh"]
