# DIC_IOT

Async Python engine simulating 200 IoT rooms (1 building x 10 floors x 20 rooms) publishing sensor data over MQTT.

## Run from repo root

```bash
docker compose up --build
```

## UI Dashboard

After containers start, open:

- http://localhost:8501

The dashboard reads the same SQLite volume used by the engine and shows:

- `room_id`
- `last_temp`
- `last_humidity`
- `hvac_mode`
- `target_temp`
- `last_update`

If the table is empty, wait one publish cycle (`PUBLISH_INTERVAL`) and refresh.

## Testing live sensor data

From a second terminal, subscribe to all sensor topics:

```bash
docker run --rm --network dic_iot_iot_net eclipse-mosquitto:2 \
  mosquitto_sub -h mosquitto -t "campus/#" -v
```

You will see per-room messages on four topics each tick.

If you installed Mosquitto locally you can also use:

```bash
mosquitto_sub -h localhost -t "campus/#" -v
```

## Send an HVAC command

```bash
mosquitto_pub -h localhost \
  -t "campus/b01/floor_01/room_001/actuator/hvac" \
  -m '{"hvac_mode":"ECO"}'
```

Valid modes: `ON`, `OFF`, `ECO`.

To reduce noise, subscribe to one room only:

```bash
mosquitto_sub -h localhost -t "campus/b01/floor_01/room_001/sensor/#" -v
```

## Configuration (`.env`)

Safe to keep defaults.

| Variable | Default | Purpose |
|---|---|---|
| `NUM_FLOORS` / `ROOMS_PER_FLOOR` | `10` / `20` | Fleet size |
| `ALPHA` / `BETA` | `0.05` / `0.3` | Thermal leakage / HVAC impact |
| `OUTSIDE_TEMP` | `20.0` | Ambient temperature (C) |
| `DEFAULT_TARGET_TEMP` | `24.0` | Room setpoint (C) |
| `PUBLISH_INTERVAL` | `5` | Seconds per tick |
| `MQTT_HOST` / `MQTT_PORT` | `mosquitto` / `1883` | Broker address |
