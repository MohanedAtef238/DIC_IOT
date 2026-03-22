class TemperatureCalculator:
    # T_new = T_room + leakage + actuator_impact + occupancy_heat -- reference
    LIGHT_THRESHOLD = 300
    OCCUPANCY_HEAT = 0.1

    def __init__(self, initial_temp: float = 22.0, setpoint: float = 22.0,
                 alpha: float = 0.01, beta: float = 0.1):
        self.alpha = alpha
        self.beta = beta
        self.setpoint = setpoint
        self.temperature = initial_temp
        self.hvac_mode = "OFF"
        self.is_occupied = False
        self.light_level = 0

    def set_hvac(self, mode: str) -> None:
        if mode in ("ON", "OFF", "ECO"):
            self.hvac_mode = mode

    def set_occupancy(self, occupied: bool) -> None:
        self.is_occupied = occupied
        self._enforce_light_correlation()

    def set_light(self, level: int) -> None:
        self.light_level = level
        self._enforce_light_correlation()

    def tick(self, outside_temp: float) -> float:
        leakage = self.alpha * (outside_temp - self.temperature)

        if self.hvac_mode == "ON":
            hvac_power = 1.0
        elif self.hvac_mode == "ECO":
            hvac_power = 0.5
        else:
            hvac_power = 0.0

        if hvac_power > 0.0 and self.temperature != self.setpoint:
            direction = 1.0 if self.setpoint > self.temperature else -1.0
            actuator_impact = self.beta * hvac_power * direction
        else:
            actuator_impact = 0.0

        occupancy_heat = self.OCCUPANCY_HEAT if self.is_occupied else 0.0

        self.temperature = round(
            self.temperature + leakage + actuator_impact + occupancy_heat, 2
        )
        return self.temperature

    def _enforce_light_correlation(self) -> None:
        if self.is_occupied and self.light_level < self.LIGHT_THRESHOLD:
            self.light_level = self.LIGHT_THRESHOLD