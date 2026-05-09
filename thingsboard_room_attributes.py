import os
import math
import requests

TB_URL = os.getenv("TB_URL", "http://localhost:8080")
TB_USER = os.getenv("TB_USER", "")
TB_PASSWORD = os.getenv("TB_PASSWORD", "")

ROOMS_PER_FLOOR = 20
TOTAL_ROOMS = 200

# Room metadata defaults. 
DEFAULT_SQUARE_FOOTAGE = 45
DEFAULT_OCCUPANT_CAPACITY = 30
ROOM_TYPES = ["lecture_hall", "lab", "office", "corridor"]

DRY_RUN = False


def login() -> str:
    url = f"{TB_URL}/api/auth/login"
    payload = {"username": TB_USER, "password": TB_PASSWORD}
    res = requests.post(url, json=payload)
    res.raise_for_status()
    return res.json()["token"]


def get_room_assets(headers):
    rooms = []
    page = 0
    while True:
        url = f"{TB_URL}/api/tenant/assets?pageSize=100&page={page}&type=room"
        res = requests.get(url, headers=headers)
        res.raise_for_status()
        data = res.json()
        rooms.extend(data.get("data", []))
        if not data.get("hasNext"):
            break
        page += 1
    return rooms



def build_attributes(room_number: int):
    index_in_floor = (room_number - 1) % ROOMS_PER_FLOOR
    room_type = ROOM_TYPES[index_in_floor % len(ROOM_TYPES)]
    square_footage = DEFAULT_SQUARE_FOOTAGE + (index_in_floor % 5) * 5
    occupant_capacity = DEFAULT_OCCUPANT_CAPACITY + (index_in_floor % 4) * 5
    return {
        "square_footage": square_footage,
        "occupant_capacity": occupant_capacity,
        "room_type": room_type
    }


def push_attributes(asset_id: str, attributes: dict, headers):
    url = f"{TB_URL}/api/plugins/telemetry/ASSET/{asset_id}/attributes/SERVER_SCOPE"
    if DRY_RUN:
        print(f"DRY_RUN asset={asset_id} attrs={attributes}")
        return
    res = requests.post(url, json=attributes, headers=headers)
    res.raise_for_status()


def parse_room_number(name: str) -> int:
    # Expected name format: Room-R001
    if "-R" not in name:
        return -1
    suffix = name.split("-R")[-1]
    try:
        return int(suffix)
    except ValueError:
        return -1


def main():
    if not TB_USER or not TB_PASSWORD:
        raise SystemExit("Set TB_USER and TB_PASSWORD env vars before running.")

    token = login()
    headers = {
        "Content-Type": "application/json",
        "X-Authorization": f"Bearer {token}"
    }

    rooms = get_room_assets(headers)
    if len(rooms) == 0:
        raise SystemExit("No room assets found. Create them first.")

    for room in rooms:
        room_number = parse_room_number(room.get("name", ""))
        if room_number <= 0 or room_number > TOTAL_ROOMS:
            print(f"Skipping unrecognized room name: {room.get('name')}")
            continue

        attributes = build_attributes(room_number)
        asset_id = room["id"]["id"] if isinstance(room.get("id"), dict) else room.get("id")
        push_attributes(asset_id, attributes, headers)
        print(f"Updated {room.get('name')} -> {attributes}")


if __name__ == "__main__":
    main()
