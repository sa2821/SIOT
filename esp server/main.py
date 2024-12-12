import network
import socket
import time
from time import sleep, localtime, time
import ntptime
import urequests
import json
import _thread

# Wi-Fi Configuration
SSID = "SKYEDAX6"
PASSWORD = "GigLrKFi7AtLXz"

# Firebase Configuration
FIREBASE_URL = "https://siot-plant-health-default-rtdb.europe-west1.firebasedatabase.app"

# Sunrise-Sunset API Configuration
SUNRISE_SUNSET_API = "https://api.sunrise-sunset.org/json"
LATITUDE = "51.5074"  # London's latitude
LONGITUDE = "-0.1278"  # London's longitude
sunrise_time = None
sunset_time = None
last_sunrise_sunset_update = 0

# Soil Moisture Threshold for Pump Activation
MOISTURE_THRESHOLD = 2000

# List to store discovered ESP32 devices and associated plant IDs
esp32_devices = []
UDP_PORT = 12345

# Periodic sensor data collection interval (in seconds)
DATA_COLLECTION_INTERVAL = 600  # 10 minutes


# Connect to Wi-Fi
def connect_to_wifi():
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    wlan.connect(SSID, PASSWORD)
    print("Connecting to Wi-Fi...")
    while not wlan.isconnected():
        sleep(1)
    print("Connected to Wi-Fi!")
    print(f"IP Address: {wlan.ifconfig()[0]}")


# Synchronize Time Using NTP
def sync_time():
    try:
        print("Synchronizing time with NTP server...")
        ntptime.settime()
        print("Time synchronized!")
    except Exception as e:
        print(f"Failed to synchronize time: {e}")

# Fetch Sunrise and Sunset Times
def fetch_sunrise_sunset():
    global sunrise_time, sunset_time, last_sunrise_sunset_update
    try:
        print("Fetching sunrise and sunset times...")
        url = f"{SUNRISE_SUNSET_API}?lat={LATITUDE}&lng={LONGITUDE}&formatted=0"
        response = urequests.get(url, timeout=10)
        data = response.json()
        
        # Log the raw API response
        print(f"Raw Sunrise-Sunset API Response: {data}")
        
        if data["status"] == "OK":
            sunrise_time = parse_time(data["results"]["sunrise"])
            sunset_time = parse_time(data["results"]["sunset"])
            last_sunrise_sunset_update = time()
            
            # Log parsed sunrise and sunset times
            print(f"Parsed Sunrise Time (minutes from midnight): {sunrise_time}")
            print(f"Parsed Sunset Time (minutes from midnight): {sunset_time}")
        else:
            print(f"Error fetching sunrise/sunset data: {data['status']}")
    except Exception as e:
        print(f"Error in fetch_sunrise_sunset: {e}")


# Parse UTC Time into Minutes from Midnight
def parse_time(utc_time_str):
    try:
        print(f"Parsing UTC time: {utc_time_str}")  # Debug log
        time_part = utc_time_str.split("T")[1].split("+")[0]  # Extract time part (e.g., "07:42:00")
        hours, minutes, _ = map(int, time_part.split(":"))  # Extract hours and minutes
        total_minutes = hours * 60 + minutes  # Convert to total minutes from midnight
        print(f"Parsed UTC time to minutes from midnight: {total_minutes}")
        return total_minutes
    except Exception as e:
        print(f"Error parsing UTC time: {e}")
        return None

    
# Check if the Current Time is During Daylight
def is_daylight():
    global sunrise_time, sunset_time, last_sunrise_sunset_update
    current_time = localtime()
    current_minutes = current_time[3] * 60 + current_time[4]  # Convert current time to minutes from midnight
    
    # Log current time and daylight check
    print(f"Current Time (minutes from midnight): {current_minutes}")
    print(f"Sunrise Time: {sunrise_time}, Sunset Time: {sunset_time}")
    
    # Update sunrise/sunset times if a day has passed
    if time() - last_sunrise_sunset_update > 24 * 3600:
        print("Refreshing sunrise and sunset times as a day has passed.")
        fetch_sunrise_sunset()

    if sunrise_time is None or sunset_time is None:
        print("Sunrise/Sunset times not available. Defaulting to daylight.")
        return True

    is_day = sunrise_time <= current_minutes <= sunset_time
    print(f"Is it daylight? {is_day}")
    return is_day

# Calculate moisture threshold based on watering suggestions
def get_moisture_threshold(watering_min):
    if watering_min == 1:
        return 3500
    elif watering_min == 2:
        return 3000
    elif watering_min == 3:
        return 2500
    else:
        return 2000  # Default threshold

# Scan for ESP32 devices
def scan_network():
    print("Scanning the network for ESP32 devices...")
    network_prefix = "192.168.0"
    devices = []
    ranges = list(range(160, 163)) # shortened list with only my esp devices
    # in future all devices in the network can be scanned

    for i in ranges:
        ip = f"{network_prefix}.{i}"
        try:
            print(f"Checking {ip}...")
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.settimeout(10)
            s.sendto(b"identify", (ip, UDP_PORT))
            data, _ = s.recvfrom(1024)
            if data.decode().strip() == "ESP32":
                print(f"ESP32 identified at {ip}")
                devices.append(ip)
            s.close()
        except Exception as e:
            print(f"Error reaching {ip}: {e}")
    print(f"Discovered devices: {devices}")
    return devices


# Fetch sensor readings from a device
def get_sensor_readings(ip):
    try:
        print(f"Fetching sensor data from {ip}...")
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(15)  # Set timeout for receiving data
        s.sendto(b"read", (ip, UDP_PORT))
        data, _ = s.recvfrom(1024)
        s.close()
        decoded_data = data.decode()
        print(f"Data received from {ip}: {decoded_data}")
        return decoded_data
    except OSError as e:
        # Handle timeout and other socket errors
        if str(e) == "ETIMEDOUT":
            print(f"Timeout while waiting for data from {ip}.")
        else:
            print(f"Error fetching data from {ip}: {e}")
        return None
    except Exception as e:
        print(f"Unexpected error fetching data from {ip}: {e}")
        return None

# Parse raw sensor data
def parse_sensor_data(sensor_data):
    try:
        print(f"Raw sensor data: {sensor_data}")
        parts = sensor_data.split(", ")
        soil_moisture = parts[0].split(": ")[1].strip()

        # Only collect light intensity during daylight hours
        light_intensity = None
        if is_daylight():
            light_intensity = parts[1].split(": ")[1].replace(" lux", "").strip()

        parsed_data = {
            "soilMoisture": int(soil_moisture),
            "lightIntensity": float(light_intensity) if light_intensity else None,
        }
        print(f"Parsed sensor data: {parsed_data}")
        return parsed_data
    except Exception as e:
        print(f"Error parsing sensor data: {e}")
        return None

# Send sensor data to Firebase
def send_sensor_data_to_firebase(plant_id, sensor_data):
    try:
        current_time = localtime()
        time_str = f"{current_time[3]:02d}:{current_time[4]:02d}"  # HH:MM
        time_key = time_str.replace(":", "_")

        print(f"Sending data to Firebase for plant {plant_id}: {sensor_data}")
        firebase_path = f"{FIREBASE_URL}/plant-images/{plant_id}/sensorData/{time_key}.json"
        response = urequests.put(firebase_path, json=sensor_data)
        print(f"Firebase response: {response.text}")
        response.close()
    except Exception as e:
        print(f"Error sending sensor data to Firebase: {e}")


# Assign ESP device to a plant
def assign_device_to_plant(device_ip, plant_id):
    try:
        print(f"Assigning device {device_ip} to plant {plant_id}")
        firebase_path = f"{FIREBASE_URL}/plant-images/{plant_id}/deviceId.json"
        response = urequests.put(firebase_path, json=device_ip)
        print(f"Assigned device {device_ip} to plant {plant_id}. Firebase Response: {response.text}")
        response.close()
    except Exception as e:
        print(f"Error assigning device to plant: {e}")


# Trigger pump
def trigger_pump(ip, plant_id, watering_min, current_moisture):
    """
    Triggers the pump based on the plant's minimum watering requirement and current moisture level.

    Args:
        ip (str): The IP address of the ESP32 device controlling the pump.
        plant_id (str): The unique ID of the plant.
        watering_min (int): The watering minimum level (1 to 4).
        current_moisture (int): The current soil moisture value.
    """
    try:
        # Determine the moisture threshold for the plant
        moisture_threshold = get_moisture_threshold(watering_min)

        # Check if the current moisture level is below the threshold
        if current_moisture < moisture_threshold:
            print(f"Moisture level {current_moisture} is below the threshold {moisture_threshold}. Triggering pump for plant {plant_id}...")

            # Send trigger command to the client device
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.sendto(b"trigger_pump", (ip, UDP_PORT))
            s.close()

            # Update the last pump activation timestamp in Firebase
            current_timestamp = int(time.time())
            firebase_path = f"{FIREBASE_URL}/plant-images/{plant_id}/lastPumpActivation.json"
            update_response = urequests.put(firebase_path, json=current_timestamp, timeout=10)
            if update_response.status_code == 200:
                print(f"Updated last pump activation for plant {plant_id} to {current_timestamp}.")
            else:
                print(f"Failed to update last pump activation for plant {plant_id}: {update_response.status_code}")
        else:
            print(f"Moisture level {current_moisture} is sufficient ({moisture_threshold}). Pump not triggered for plant {plant_id}.")

    except Exception as e:
        print(f"Error triggering pump for plant {plant_id} at {ip}: {e}")

# Start sensor data collection immediately for a newly assigned device
def collect_sensor_data_for_device(device_ip, plant_id):
    print(f"Starting immediate data collection for device {device_ip}, plant ID: {plant_id}")
    sensor_data = get_sensor_readings(device_ip)
    if sensor_data:
        parsed_data = parse_sensor_data(sensor_data)
        if parsed_data:
            send_sensor_data_to_firebase(plant_id, parsed_data)

            # Fetch watering suggestions and adjust moisture threshold dynamically
            plant_ref = f"{FIREBASE_URL}/plant-images/{plant_id}.json"
            response = urequests.get(plant_ref)
            if response.status_code == 200:
                plant_data = response.json()
                watering_min = plant_data.get("watering", {}).get("min", None)
                if watering_min is None:
                    print(f"No valid watering minimum found for plant {plant_id}. Setting default watering minimum to 2.")
                    watering_min = 2  # Set a default value
                    trigger_pump(
                        ip=device_ip,
                        plant_id=plant_id,
                        watering_min=watering_min,
                        current_moisture=parsed_data["soilMoisture"],
                    )
                else:
                    print(f"No valid watering minimum found for plant {plant_id}.")
            else:
                print(f"Failed to fetch plant data for {plant_id}. Response code: {response.status_code}")
        else:
            print(f"Failed to parse sensor data from {device_ip}.")
    else:
        print(f"No sensor data received from {device_ip}.")


# Periodic Sensor Data Collection
def periodic_sensor_data_collection():
    while True:
        if esp32_devices:
            print("Starting periodic data collection...")
            for device in esp32_devices:
                ip = device["ip"]
                plant_id = device["plantId"]
                collect_sensor_data_for_device(ip, plant_id)
        else:
            print("No devices in the list for data collection.")

        print(f"Sleeping for {DATA_COLLECTION_INTERVAL} seconds before the next collection.")
        sleep(DATA_COLLECTION_INTERVAL)


# Handle HTTP Requests
# Handle HTTP Requests
def handle_http_request(cl):
    global esp32_devices
    try:
        request = cl.recv(1024).decode("utf-8")
        print("Raw HTTP Request:", request)

        # Handle preflight OPTIONS requests
        if "OPTIONS" in request:
            response = (
                "HTTP/1.1 204 No Content\r\n"
                "Access-Control-Allow-Origin: *\r\n"
                "Access-Control-Allow-Methods: POST, GET, OPTIONS\r\n"
                "Access-Control-Allow-Headers: Content-Type\r\n"
                "Content-Length: 0\r\n\r\n"
            )
            cl.send(response)
            cl.close()
            return

        # Extract request body
        request_body = ""
        if "\r\n\r\n" in request:
            request_body = request.split("\r\n\r\n", 1)[1]

        print("Extracted Request Body:", request_body)

        # Parse JSON body
        try:
            data = json.loads(request_body) if request_body.strip() else {}
        except json.JSONDecodeError as e:
            print(f"Error decoding JSON: {e}")
            cl.send(
                "HTTP/1.1 400 Bad Request\r\n"
                "Access-Control-Allow-Origin: *\r\n"
                "Content-Type: text/plain\r\n\r\n"
                "Invalid JSON"
            )
            cl.close()
            return

        # Handle /trigger-scan endpoint
        if "/trigger-scan" in request:
            plant_id = data.get("plantId")
            if not plant_id:
                print("Missing plantId in JSON payload")
                cl.send(
                    "HTTP/1.1 400 Bad Request\r\n"
                    "Access-Control-Allow-Origin: *\r\n"
                    "Content-Type: text/plain\r\n\r\n"
                    "Missing plantId"
                )
                cl.close()
                return

            print(f"Received scan trigger for plant ID: {plant_id}")
            new_devices = scan_network()
            if new_devices:
                device_ip = new_devices[0]
                assign_device_to_plant(device_ip, plant_id)
                esp32_devices.append({"ip": device_ip, "plantId": plant_id})
                collect_sensor_data_for_device(device_ip, plant_id)  # Immediate data collection
                response = (
                    "HTTP/1.1 200 OK\r\n"
                    "Access-Control-Allow-Origin: *\r\n"
                    "Content-Type: application/json\r\n\r\n"
                    '{"success": true, "message": "Scan started successfully"}'
                )
            else:
                response = (
                    "HTTP/1.1 200 OK\r\n"
                    "Access-Control-Allow-Origin: *\r\n"
                    "Content-Type: application/json\r\n\r\n"
                    '{"success": false, "message": "No devices found"}'
                )
            cl.send(response)
            return

        # Handle /trigger-pump endpoint
        if "/trigger-pump" in request:
            device_id = data.get("deviceId")
            plant_id = data.get("plantId")
            if not device_id:
                print("Missing deviceId in JSON payload")
                cl.send(
                    "HTTP/1.1 400 Bad Request\r\n"
                    "Access-Control-Allow-Origin: *\r\n"
                    "Content-Type: text/plain\r\n\r\n"
                    "Missing deviceId"
                )
                cl.close()
                return

            print(f"Received pump trigger request for device ID: {device_id}")
            trigger_pump(device_id)
            response = (
                "HTTP/1.1 200 OK\r\n"
                "Access-Control-Allow-Origin: *\r\n"
                "Content-Type: application/json\r\n\r\n"
                '{"success": true, "message": "Pump triggered successfully"}'
            )
            cl.send(response)
            return

        # Default response for unknown endpoints
        response = (
            "HTTP/1.1 404 Not Found\r\n"
            "Access-Control-Allow-Origin: *\r\n"
            "Content-Type: text/plain\r\n\r\n"
            "Endpoint Not Found"
        )
        cl.send(response)

    except Exception as e:
        print(f"Error handling HTTP request: {e}")
        cl.send(
            "HTTP/1.1 500 Internal Server Error\r\n"
            "Access-Control-Allow-Origin: *\r\n"
            "Content-Type: text/plain\r\n\r\n"
            "Server Error"
        )
    finally:
        cl.close()



# Main Event Loop
def main_loop():
    addr = socket.getaddrinfo("0.0.0.0", 80)[0][-1]
    s = socket.socket()
    s.bind(addr)
    s.listen(5)
    print("HTTP server running...")

    while True:
        try:
            cl, addr = s.accept()
            print(f"Connection from {addr}")
            handle_http_request(cl)
        except OSError as e:
            print(f"HTTP server error: {e}")


# Main Program
def main():
    connect_to_wifi()
    sync_time()
    fetch_sunrise_sunset()
    _thread.start_new_thread(periodic_sensor_data_collection, ())
    main_loop()


# Run the main program
main()
