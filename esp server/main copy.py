import network
import socket
from time import sleep, localtime
import ntptime
import os
import urequests
import json

# Wi-Fi Configuration
SSID = "SKYEDAX6"
PASSWORD = "GigLrKFi7AtLXz"

# Sunrise-Sunset API
SUNRISE_SUNSET_API = "https://api.sunrise-sunset.org/json"
LATITUDE = "51.5074"  # Example: London's latitude
LONGITUDE = "-0.1278"  # Example: London's longitude
sunrise_time = None
sunset_time = None

# Firebase Configuration
FIREBASE_URL = "https://siot-plant-health-default-rtdb.europe-west1.firebasedatabase.app"

# List to store discovered ESP32 devices
esp32_devices = []
UDP_PORT = 12345

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

# Fetch Sunrise & Sunset Times
def fetch_sunrise_sunset():
    global sunrise_time, sunset_time
    try:
        print("Fetching sunrise and sunset times...")
        url = f"{SUNRISE_SUNSET_API}?lat={LATITUDE}&lng={LONGITUDE}&formatted=0"
        response = urequests.get(url)
        data = response.json()
        if data["status"] == "OK":
            sunrise_time = parse_time(data["results"]["sunrise"])
            sunset_time = parse_time(data["results"]["sunset"])
            print(f"Sunrise: {sunrise_time}, Sunset: {sunset_time}")
        else:
            print(f"Error fetching sunrise/sunset data: {data['status']}")
    except Exception as e:
        print(f"Error in fetch_sunrise_sunset: {e}")

# Parse UTC time into minutes from midnight
def parse_time(utc_time_str):
    try:
        # Example UTC time: "2024-12-01T07:42:00+00:00"
        time_part = utc_time_str.split("T")[1].split("+")[0]  # Extract "07:42:00"
        hours, minutes, _ = map(int, time_part.split(":"))  # Extract hours and minutes
        # Adjust to local time (assuming 0 offset for simplicity, update if needed)
        local_hours = (hours + 0) % 24  # Replace `0` with your timezone offset
        return local_hours * 60 + minutes  # Convert to total minutes from midnight
    except Exception as e:
        print(f"Error parsing UTC time: {e}")
        return None


# Check if the current time is during daylight
def is_daylight():
    if sunrise_time is None or sunset_time is None:
        print("Sunrise/Sunset times not available.")
        return True  # Default to collecting data
    current_time = localtime()
    current_minutes = current_time[3] * 60 + current_time[4]  # Current time in minutes from midnight
    return sunrise_time <= current_minutes <= sunset_time

# Scan for ESP32 devices
def scan_network():
    print("Scanning the network for ESP32 devices...")
    network_prefix = "192.168.0"
    devices = []
    ranges = list(range(110, 113)) + list(range(160, 163))

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
    return devices

# Write data to Firebase
def send_to_firebase(time_str, soil_moisture, light_intensity, client_ip, plant_id=None):
    try:
        # Format client IP for Firebase (replace dots with underscores)
        client_ip_key = client_ip.replace('.', '_')

        # Prepare time key
        time_key = time_str.replace(':', '_')[:5]  # Format as HH_MM

        # Prepare data payload
        data = {
            "time": time_str,
            "soilMoisture": int(float(soil_moisture)),
            "lightIntensity": float(light_intensity),
        }

        # Firebase path for sensor data
        if plant_id:
            firebase_path = f"{FIREBASE_URL}/plant-images/{plant_id}/sensorData/{time_key}.json"
        else:
            firebase_path = f"{FIREBASE_URL}/readings/{client_ip_key}/{time_key}.json"

        # Send data to Firebase
        response = urequests.put(firebase_path, json=data)
        print(f"Firebase Response: {response.text}")
        response.close()
    except Exception as e:
        print(f"Error sending data to Firebase: {e}")

# HTTP Server to Trigger Scans
def start_http_server():
    addr = socket.getaddrinfo("0.0.0.0", 80)[0][-1]
    s = socket.socket()
    s.bind(addr)
    s.listen(5)
    print("Listening for HTTP requests...")

    while True:
        cl, addr = s.accept()
        print(f"Connection from {addr}")
        request = cl.recv(1024).decode()
        if "/scan" in request:
            print("Triggering network scan...")
            new_devices = scan_network()
            esp32_devices.extend(new_devices)
            response = "HTTP/1.1 200 OK\r\n\r\nNetwork scan completed!"
        else:
            response = "HTTP/1.1 404 Not Found\r\n\r\nRoute not found."
        cl.send(response)
        cl.close()

# Fetch the latest plant added to Firebase
def get_latest_plant():
    try:
        firebase_path = f"{FIREBASE_URL}/plant-images.json?orderBy=\"createdAt\"&limitToLast=1"
        response = urequests.get(firebase_path)
        data = response.json()
        if data:
            plant_id = list(data.keys())[0]  # Get the latest plant's ID
            print(f"Latest plant ID: {plant_id}")
            return plant_id
        else:
            print("No plants found in Firebase.")
            return None
    except Exception as e:
        print(f"Error fetching latest plant: {e}")
        return None

# Fetch sensor readings via UDP
def get_sensor_readings(ip):
    try:
        print(f"Fetching sensor data from {ip}...")
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(10)
        s.sendto(b"read", (ip, UDP_PORT))
        data, _ = s.recvfrom(1024)
        s.close()
        print(f"Data received from {ip}: {data.decode()}")
        return data.decode()
    except Exception as e:
        print(f"Error fetching data from {ip}: {e}")
        return None

# Main Program
def main():
    connect_to_wifi()
    sync_time()
    fetch_sunrise_sunset()

    # Data collection loop
    while True:
        # Check if daylight
        if not is_daylight():
            print("It's nighttime. Skipping light intensity data collection.")
            sleep(600)  # Wait 10 minutes and check again
            continue

        # Fetch the latest plant
        print("Fetching the latest plant...")
        latest_plant_id = get_latest_plant()
        if not latest_plant_id:
            print("No new plant detected. Waiting...")
            sleep(10)
            continue

        # Scan the network for new ESP devices
        print("Scanning for ESP32 devices...")
        new_devices = scan_network()
        if not new_devices:
            print("No new devices found. Retrying later...")
            sleep(600)
            continue

        # Assign the first discovered device to the latest plant
        new_device_ip = new_devices[0]
        esp32_devices.append({"ip": new_device_ip, "plantId": latest_plant_id})

        # Collect and send sensor data
        print("Starting data collection...")
        for device in esp32_devices:
            ip = device["ip"]
            plant_id = device["plantId"]
            sensor_data = get_sensor_readings(ip)
            if sensor_data:
                try:
                    parts = sensor_data.split(", ")
                    soil_moisture = parts[0].split(": ")[1].strip()
                    light_intensity = parts[1].split(": ")[1].replace(" lux", "").strip()

                    # Get current time
                    current_time = localtime()
                    time_str = f"{current_time[3]:02d}:{current_time[4]:02d}"

                    # Send data to Firebase
                    send_to_firebase(time_str, soil_moisture, light_intensity, ip, plant_id)
                except Exception as e:
                    print(f"Error processing sensor data: {e}")
            else:
                print(f"Failed to retrieve data from {ip}")

        print("Data collection complete. Waiting for the next cycle...")
        sleep(600)

# Run the main program
main()
