import requests

THINGSBOARD_URL = "http://localhost:8080"

EMAIL = ""
PASSWORD = ""


# ---------------------------
# 1. LOGIN TO GET TOKEN
# ---------------------------
def login():
    url = f"{THINGSBOARD_URL}/api/auth/login"
    payload = {
        "username": EMAIL,
        "password": PASSWORD
    }

    response = requests.post(url, json=payload)

    if response.status_code == 200:
        token = response.json()["token"]
        print("Login successful")
        return token
    else:
        print("Login failed:", response.text)
        return None


# ---------------------------
# 2. CREATE ASSET
# ---------------------------
def create_asset(name, asset_type, headers):
    url = f"{THINGSBOARD_URL}/api/asset"

    payload = {
        "name": name,
        "type": asset_type
    }

    response = requests.post(url, json=payload, headers=headers)

    if response.status_code == 200:
        print(f"Created: {name}")
        return response.json()
    else:
        print(f"Failed: {name} -> {response.text}")
        return None


# ---------------------------
# MAIN FLOW
# ---------------------------
token = login()

if not token:
    exit()

headers = {
    "Content-Type": "application/json",
    "X-Authorization": f"Bearer {token}"
}

# ---------------------------
# Create Floors (Floor-Fxx)
# ---------------------------
NUM_FLOORS = 10
floors = []

for i in range(1, NUM_FLOORS + 1):
    floor_name = f"Floor-F{i:02d}"
    floor = create_asset(floor_name, "floor", headers)
    if floor:
        floors.append(floor)


# ---------------------------
# Create Rooms (Room-Rxxx)
# ---------------------------
NUM_ROOMS = 200

for i in range(1, NUM_ROOMS + 1):
    room_name = f"Room-R{i:03d}"
    create_asset(room_name, "room", headers)