def room_base_topic(floor, room_num):
    return f"campus/bldg_01/floor_{floor:02d}/room_{room_num:03d}"


def room_payload_topic(base_topic):
    return f"{base_topic}/payload"


def room_sensor_topic(base_topic, sensor_name):
    return f"{base_topic}/sensor/{sensor_name}"


def room_hvac_command_topic(base_topic):
    return f"{base_topic}/actuator/hvac"


def all_room_payload_topics():
    return "campus/bldg_01/+/+/payload"


def all_room_hvac_command_topics():
    return "campus/bldg_01/+/+/actuator/hvac"
