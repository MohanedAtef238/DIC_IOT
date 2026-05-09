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

## ThingsBoard Disk Growth

When a ThingsBoard restore suddenly consumes multiple GB, the growth is usually in PostgreSQL data under the Docker volume backing `/data/db`, especially `/data/db/base` and `/data/db/pg_wal`.

### Safe cleanup steps

Do not delete files from `pg_wal` manually. PostgreSQL manages that directory itself.

1. Inspect usage first:

```bash
docker system df -v
docker ps -a --size
docker exec mytb sh -c "du -sh /data/db/base /data/db/pg_wal /var/log/thingsboard 2>/dev/null"
```

2. Stop writes into ThingsBoard before cleanup:

```bash
docker compose stop nodered_master engine
```

3. Ask PostgreSQL to flush WAL naturally:

```bash
docker exec mytb psql -U postgres -d thingsboard -c "CHECKPOINT;"
```

4. If `pg_wal` stays large after restore, restart ThingsBoard cleanly:

```bash
docker compose restart mytb
```

5. Remove Docker build cache when you no longer need cached image layers:

```bash
docker builder prune -a
```

6. Remove unused Docker resources only if you are sure they are disposable:

```bash
docker system prune
docker volume prune
```

7. Remove old restore volumes only after confirming they are not needed:

```bash
docker volume ls
docker volume rm <old_tb_volume_name>
```

### Fresh-volume restore workflow

This repo now supports overriding the ThingsBoard volume names with environment variables:

- `TB_DATA_VOLUME`
- `TB_LOGS_VOLUME`

That lets you restore into a brand-new volume each time instead of inflating the current long-lived database.

#### Start ThingsBoard on a fresh restore volume

PowerShell:

```powershell
$env:TB_DATA_VOLUME="dic_iot_mytb_restore_20260509"
$env:TB_LOGS_VOLUME="dic_iot_mytb_restore_20260509_logs"
docker compose up -d mytb
```

Bash:

```bash
TB_DATA_VOLUME=dic_iot_mytb_restore_20260509 \
TB_LOGS_VOLUME=dic_iot_mytb_restore_20260509_logs \
docker compose up -d mytb
```

Then perform the restore inside that fresh ThingsBoard instance.

#### Bring up the rest of the stack against the restored volume

Use the same environment variables when starting the rest of the stack:

PowerShell:

```powershell
docker compose up -d
```

Bash:

```bash
docker compose up -d
```

As long as `TB_DATA_VOLUME` and `TB_LOGS_VOLUME` stay set in that shell, the stack keeps using the restored TB data.

#### Roll back safely to the original volume

If the restore is bad, stop the stack and clear the overrides:

PowerShell:

```powershell
docker compose down
Remove-Item Env:TB_DATA_VOLUME -ErrorAction SilentlyContinue
Remove-Item Env:TB_LOGS_VOLUME -ErrorAction SilentlyContinue
docker compose up -d mytb
```

Bash:

```bash
docker compose down
unset TB_DATA_VOLUME
unset TB_LOGS_VOLUME
docker compose up -d mytb
```

The original persistent volume names used by this repo are:

- `dic_iot_mytb_data`
- `dic_iot_mytb_logs`
