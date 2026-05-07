import requests
import json
import sys

# Using localhost since mytb is mapped to 8080 on the host
TB_URL = "http://localhost:8080"

# If it expires, the script will fail and we can try login with fallback creds.
TOKEN = "eyJhbGciOiJIUzUxMiJ9.eyJzdWIiOiJtYWlsQG1haWwuY29tIiwidXNlcklkIjoiNTdkNmRlNzAtNDhhMS0xMWYxLThlZWItOTNiMTBiNzgyMDRjIiwic2NvcGVzIjpbIlRFTkFOVF9BRE1JTiJdLCJzZXNzaW9uSWQiOiI2ZDkyMjQ5ZS05N2Y1LTQzMmQtYWRkNS03YTI3MjY1NzA2NjYiLCJleHAiOjE3NzgxMjczNjQsImlzcyI6InRoaW5nc2JvYXJkLmlvIiwiaWF0IjoxNzc4MTE4MzY0LCJmaXJzdE5hbWUiOiJtYWlsIiwibGFzdE5hbWUiOiJtYWlsIiwiZW5hYmxlZCI6ZmFsc2UsImlzUHVibGljIjpmYWxzZSwidGVuYW50SWQiOiI1MTJmNGI5MC00ODlmLTExZjEtOWJjYS0wZDUyNzMyM2I2M2QiLCJjdXN0b21lcklkIjoiMTM4MTQwMDAtMWRkMi0xMWIyLTgwODAtODA4MDgwODA4MDgwIn0.Mi3srHeNyHulnScm2y-hDuhJD0oq6oeQVRihUVOH9TfjkQDIi8plGTZrNWYb9JVbI1PJkejEjR_WoWYiGlc-wQ"

headers = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}

def provision():
    try:
        # 1. Check if token works
        print("Connecting to ThingsBoard...")
        res = requests.get(f"{TB_URL}/api/auth/user", headers=headers)
        if res.status_code != 200:
            print("Provided token is invalid or expired. Attempting login...")
            # Fallback to sysadmin or other creds if needed, 
            # but user gave a token so we assume it works.
            # If login is needed, user should provide creds for mail@mail.com.
            sys.exit(1)

        # 2. Check if token works
        print("Connecting to ThingsBoard...")
        res = requests.get(f"{TB_URL}/api/auth/user", headers=headers)
        if res.status_code != 200:
            print("Provided token is invalid or expired. Attempting login...")
            # Fallback to sysadmin or other creds if needed, 
            # but user gave a token so we assume it works.
            # If login is needed, user should provide creds for mail@mail.com.
            sys.exit(1)

        # 2. Get all devices (handles pagination)
        devices = []
        page = 0
        while True:
            url = f"{TB_URL}/api/tenant/devices?pageSize=100&page={page}"
            response = requests.get(url, headers=headers)
            response.raise_for_status()
            res_data = response.json()
            devices.extend(res_data["data"])
            if res_data.get("hasNext") == False:
                break
            page += 1

        print(f"Found {len(devices)} devices")

        # 3. Push initial attributes to every device
        for device in devices:
            device_id = device["id"]["id"]
            device_name = device["name"]

            # Shared attributes (what the dashboard pushes down)
            requests.post(
                f"{TB_URL}/api/plugins/telemetry/DEVICE/{device_id}/attributes/SHARED_SCOPE",
                headers=headers,
                json={
                    "config_data": "",
                    "signature": "",
                    "target_version": "1.0",
                    "target": "all"
                }
            )

            # Client attributes (what the device reports back)
            requests.post(
                f"{TB_URL}/api/plugins/telemetry/DEVICE/{device_id}/attributes/CLIENT_SCOPE",
                headers=headers,
                json={"current_version": "1.0"}
            )

            print(f"Done: {device_name}")

        print("All devices provisioned.")

    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    provision()
