# DIC_IOT

Async Python engine simulating 200 IoT rooms (1 building × 10 floors × 20 rooms) publishing sensor data over MQTT.

## Run this from the root .

```bash
docker compose up --build
```

## Testing, live sensor data

From a second terminal, subscribe to all sensor topics:

```bash
docker run --rm --network dic_iot_iot_net eclipse-mosquitto:2 \
  mosquitto_sub -h mosquitto -t "campus/#" -v
```

You'll see per-room messages on four topics each tick

If you installed Mosquitto locally you can also use (please dont do that):

```bash
mosquitto_sub -h localhost -t "campus/#" -v
```

## Send an HVAC command

```bash
mosquitto_pub -h localhost \
  -t "campus/bldg_01/floor_01/room_001/actuator/hvac" \
  -m '{"hvac_mode":"ECO"}'
```
Valid modes: `ON`, `OFF`, `ECO`. Keep in mind this will be really hard to notice in the flood of messages, so you might want to subscribe to just that room's sensor topic:

```bash
mosquitto_sub -h localhost -t "campus/bldg_01/floor_01/room_001/sensor/#" -v
```

## Configuration (`.env`) safe to keep the defaults provided.

| Variable | Default | Purpose |
|---|---|---|
| `NUM_FLOORS` / `ROOMS_PER_FLOOR` | `10` / `20` | Fleet size |
| `ALPHA` / `BETA` | `0.05` / `0.3` | Thermal leakage / HVAC impact |
| `OUTSIDE_TEMP` | `20.0` | Ambient temperature (°C) |
| `DEFAULT_TARGET_TEMP` | `24.0` | Room setpoint (°C) |
| `PUBLISH_INTERVAL` | `5` | Seconds per tick |
| `MQTT_HOST` / `MQTT_PORT` | `mosquitto` / `1883` | Broker address |

