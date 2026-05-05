const fs = require('fs');

const path = 'node-red/flows.json';
let data = fs.readFileSync(path, 'utf8');
let flows = JSON.parse(data);

// 1. Create the new tb_gateway_attributes node
const attributesNode = {
    "id": "tb_gateway_attributes",
    "type": "mqtt out",
    "z": "6db520c8e77fa5c3",
    "name": "ThingsBoard Gateway Attributes",
    "topic": "v1/gateway/attributes",
    "qos": "1",
    "retain": "",
    "respTopic": "",
    "contentType": "",
    "userProps": "",
    "correl": "",
    "expiry": "",
    "broker": "tb_direct_broker",
    "x": 1300,
    "y": 550,
    "wires": []
};
flows.push(attributesNode);

// 2. Modify uplink_formatter
let uplink = flows.find(f => f.id === 'uplink_formatter');
if (uplink) {
    uplink.outputs = 4;
    uplink.wires.push(["tb_gateway_attributes"]);
    uplink.func = uplink.func.replace(
        "return [\n    { payload: telemetry },\n    { payload: connect },\n    { payload: payload }\n];",
        `const match = payload.deviceName.match(/r(\\d+)/i);\nconst roomNumber = match ? parseInt(match[1], 10) : 0;\nconst attributes = JSON.stringify({\n    [payload.deviceName]: {\n        polygonIndex: roomNumber\n    }\n});\n\nreturn [\n    { payload: telemetry },\n    { payload: connect },\n    { payload: payload },\n    { payload: attributes }\n];`
    );
}

// 3. Modify coap_response_parser
let coapParser = flows.find(f => f.id === 'coap_response_parser');
if (coapParser) {
    coapParser.outputs = 4;
    coapParser.wires.push(["tb_gateway_attributes"]);
    coapParser.func = coapParser.func.replace(
        "return [\n    { payload: telemetry },\n    { payload: connect },\n    { payload: data }\n];",
        `const match = deviceName.match(/r(\\d+)/i);\nconst roomNumber = match ? parseInt(match[1], 10) : 0;\nconst attributes = JSON.stringify({\n    [deviceName]: {\n        polygonIndex: roomNumber\n    }\n});\n\nreturn [\n    { payload: telemetry },\n    { payload: connect },\n    { payload: data },\n    { payload: attributes }\n];`
    );
}

fs.writeFileSync(path, JSON.stringify(flows, null, 4));
console.log("Successfully modified flows.json");
