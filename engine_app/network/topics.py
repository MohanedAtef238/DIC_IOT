def room_base_topic(floor, room_num):
    return f"campus/b01/floor_{floor:02d}/room_{room_num:03d}"


def room_payload_topic(base_topic):
    return f"{base_topic}/payload"


def room_sensor_topic(base_topic, sensor_name):
    return f"{base_topic}/sensor/{sensor_name}"


def room_hvac_command_topic(base_topic):
    return f"{base_topic}/actuator/hvac"


def room_hvac_applied_ack_topic(base_topic):
    return f"{base_topic}/ack/hvac_applied"


def room_light_dimmer_command_topic(base_topic):
    return f"{base_topic}/actuator/light_dimmer"


def room_light_dimmer_applied_ack_topic(base_topic):
    return f"{base_topic}/ack/light_dimmer_applied"


def all_room_hvac_applied_ack_topics():
    return "campus/b01/+/+/ack/hvac_applied"


def all_room_payload_topics():
    return "campus/b01/+/+/payload"


def fleet_hvac_command_topic():
    return "campus/b01/actuator/hvac"

def room_heartbeat():
    return "campus/b01/health"
