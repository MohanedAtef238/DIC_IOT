def calc_temp(current, outside, alpha, beta, hvac_pwr, target, occupied):
    leakage = alpha * (outside - current)
    sign = 1 if target > current else -1
    body_heat = 0.1 if occupied else 0
    return round(current + leakage + beta * hvac_pwr * sign + body_heat, 2)