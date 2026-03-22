import asyncio, time, aiosqlite,random

class Room:
    def __init__(self, b, f, r, state=None):
        self.id = f"b{b}-f{f}-r{r}"
        self.path = f"campus/b{b}/f{f}/r{r}"
        # Restore state from SQLite if available, else default
        self.temp = state['temp'] if state else 22.0
        self.hvac = state['hvac'] if state else "OFF"

    async def run_simulation(self, mqtt, db):
        await asyncio.sleep(random.uniform(0, 5))  # Startup Jitter
        while True:
            start = time.perf_counter()

            # # 1. Physics & Persistence
            # if self.hvac == "ON":
            #     self.temp += 0.1
            # await db.execute(
            #     "REPLACE INTO states VALUES (?,?,?)",
            #     (self.id, self.temp, self.hvac)
            # )
            # await db.commit()

            # 2. Telemetry Broadcast
            payload = {
                "id": self.id,
                "ts": int(time.time()),
                "temp": round(self.temp, 2)
            }
            await mqtt.publish(f"{self.path}/telemetry", payload)

            # 3. Drift Compensation
            await asyncio.sleep(max(0, 5 - (time.perf_counter() - start)))