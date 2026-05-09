import requests
import re
import sys

THINGSBOARD_URL = "http://localhost:8080"
# Using static token from provision_ota.py
TOKEN = "eyJhbGciOiJIUzUxMiJ9.eyJzdWIiOiJodXNzZWFpbnNoYWxhYnk2QGdtYWlsLmNvbSIsInVzZXJJZCI6ImQwYjRjMDUwLTQ4NTYtMTFmMS1iODFhLWZiMzBmMmVkYjliYSIsInNjb3BlcyI6WyJURU5BTlRfQURNSU4iXSwic2Vzc2lvbklkIjoiZWU0MjcwOGMtY2E4ZC00NzExLTllNGQtYmJhNTFjN2JkZDMyIiwiZXhwIjoxNzc4MzYzOTY1LCJpc3MiOiJ0aGluZ3Nib2FyZC5pbyIsImlhdCI6MTc3ODM1NDk2NSwiZmlyc3ROYW1lIjoiSHVzc2VhaW4iLCJsYXN0TmFtZSI6IlNoYWxhYnkiLCJlbmFibGVkIjp0cnVlLCJpc1B1YmxpYyI6ZmFsc2UsInRlbmFudElkIjoiMTA1ZmYxMzAtNDg1MS0xMWYxLWI0ODYtYTVhM2YxNDZlOWJlIiwiY3VzdG9tZXJJZCI6IjEzODE0MDAwLTFkZDItMTFiMi04MDgwLTgwODA4MDgwODA4MCJ9.j6qgTkaCePDr-6mODd2tcXnuwJLnGSz7uCLIX_2tUHK2U3jUIAiGnoqHJBRpECxI6QQ4fjUo1q-cSw8Wv6FVfg"

headers = {
    "Content-Type": "application/json",
    "X-Authorization": f"Bearer {TOKEN}"
}


# ---------------------------
# TOKEN VALIDATION (Flow from provision_ota.py)
# ---------------------------
def check_token():
    print("Connecting to ThingsBoard...")
    try:
        res = requests.get(f"{THINGSBOARD_URL}/api/auth/user", headers=headers)
        if res.status_code != 200:
            print("Provided token is invalid or expired.")
            sys.exit(1)
        print("Token verified.")
    except Exception as e:
        print(f"Error connecting: {e}")
        sys.exit(1)


# ---------------------------
# GET ALL DEVICES
# ---------------------------
def get_all_devices(headers):
    devices = []
    page = 0

    while True:
        url = f"{THINGSBOARD_URL}/api/tenant/devices?pageSize=100&page={page}"
        res = requests.get(url, headers=headers).json()

        devices.extend(res["data"])

        if res["hasNext"] is False:
            break
        page += 1

    return devices


# ---------------------------
# GET ALL ROOM ASSETS
# ---------------------------
def get_all_rooms(headers):
    rooms = {}
    page = 0

    while True:
        url = f"{THINGSBOARD_URL}/api/tenant/assets?pageSize=100&page={page}&type=room"
        res = requests.get(url, headers=headers).json()

        for asset in res["data"]:
            name = asset["name"]  # Room-R117
            match = re.search(r"R(\d+)", name)
            if match:
                room_number = int(match.group(1))
                rooms[room_number] = asset

        if res["hasNext"] is False:
            break
        page += 1

    return rooms


# ---------------------------
# CREATE RELATION
# ---------------------------
def create_relation(from_id, to_id, headers):
    url = f"{THINGSBOARD_URL}/api/relation"

    payload = {
        "from": from_id,
        "to": to_id,
        "type": "Contains",
        "typeGroup": "COMMON"
    }

    res = requests.post(url, json=payload, headers=headers)

    if res.status_code == 200:
        print(f"Linked {from_id['id']} -> {to_id['id']}")
    else:
        print("Failed relation:", res.text)


# ---------------------------
# MAIN
# ---------------------------
if __name__ == "__main__":
    check_token()

devices = get_all_devices(headers)
rooms = get_all_rooms(headers)

print(f"Found {len(devices)} devices")
print(f"Found {len(rooms)} rooms")

# ---------------------------
# MATCH & LINK
# ---------------------------
for device in devices:
    device_name = device["name"]  # b01-f06-r117

    match = re.search(r"r(\d+)", device_name, re.IGNORECASE)

    if not match:
        print(f"Skipping (no room in name): {device_name}")
        continue

    room_number = int(match.group(1))

    if room_number not in rooms:
        print(f"No room asset for: {device_name}")
        continue

    room_asset = rooms[room_number]

    from_id = {
        "entityType": "ASSET",
        "id": room_asset["id"]["id"]
    }

    to_id = {
        "entityType": "DEVICE",
        "id": device["id"]["id"]
    }

    create_relation(from_id, to_id, headers)