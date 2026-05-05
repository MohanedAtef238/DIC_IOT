import requests

TB_URL = "http://localhost:8080"   # change this
USERNAME = "husseainshalaby6@gmail.com"
PASSWORD = "Husseain@2003"

RELATION_TYPE = "Contains"

session = requests.Session()


# -------------------------
# LOGIN
# -------------------------
def login():
    url = f"{TB_URL}/api/auth/login"
    payload = {"username": USERNAME, "password": PASSWORD}
    res = session.post(url, json=payload)
    res.raise_for_status()
    token = res.json()["token"]
    session.headers.update({"X-Authorization": f"Bearer {token}"})


# -------------------------
# GET ALL ASSETS
# -------------------------
def get_assets():
    url = f"{TB_URL}/api/tenant/assets?pageSize=1000&page=0"
    res = session.get(url)
    res.raise_for_status()
    return res.json()["data"]


# -------------------------
# CREATE RELATION
# -------------------------
def extract_id(entity):
    if isinstance(entity["id"], dict):
        return entity["id"]["id"]
    return entity["id"]


def create_relation(from_entity, to_entity):
    url = f"{TB_URL}/api/relation"

    from_id = extract_id(from_entity)
    to_id = extract_id(to_entity)

    payload = {
        "from": {
            "id": from_id,
            "entityType": "ASSET"
        },
        "to": {
            "id": to_id,
            "entityType": "ASSET"
        },
        "type": RELATION_TYPE,
        "typeGroup": "COMMON"
    }

    res = session.post(url, json=payload)

    if res.status_code not in [200, 201]:
        print("Failed relation:", res.text)


# -------------------------
# FIND BY NAME
# -------------------------
def find_by_name(assets, name):
    for a in assets:
        if a["name"] == name:
            return a
    return None


# -------------------------
# MAIN LOGIC
# -------------------------
def main():
    login()
    assets = get_assets()

    # Sort floors correctly (F01 → F10)
    floors = sorted(
        [a for a in assets if a["name"].startswith("Floor-F")],
        key=lambda x: int(x["name"].split("-F")[1])
    )

    rooms = sorted(
        [a for a in assets if a["name"].startswith("Room-R")],
        key=lambda x: int(x["name"].split("-R")[1])
    )

    if len(floors) != 10:
        print(f"Warning: expected 10 floors, found {len(floors)}")

    if len(rooms) != 200:
        print(f"Warning: expected 200 rooms, found {len(rooms)}")

    # Map 20 rooms per floor
    for i, floor in enumerate(floors):
        start = i * 20
        end = start + 20
        assigned_rooms = rooms[start:end]

        print(f"\n{floor['name']} → Room-R{start+1:03d} to Room-R{end:03d}")

        for room in assigned_rooms:
            create_relation(floor["id"], room["id"])
            print(f"  {floor['name']} -> {room['name']}")


if __name__ == "__main__":
    main()