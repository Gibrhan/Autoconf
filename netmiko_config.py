import yaml
from netmiko import ConnectHandler

DEVICES_FILE = "devices.yaml"

def load_devices():
    try:
        with open(DEVICES_FILE, "r") as f:
            data = yaml.safe_load(f) or {}
            return data.get("devices", [])
    except FileNotFoundError:
        return []

def save_devices(devices):
    with open(DEVICES_FILE, "w") as f:
        yaml.dump(devices, f)

def configure_device(device, commands):
    try:
        connection = ConnectHandler(
            device_type=device["device_type"],
            host=device["ip"],
            username=device["username"],
            password=device["password"]
        )
        output = connection.send_config_set(commands)
        connection.save_config()
        connection.disconnect()
        return output
    except Exception as e:
        return f"Error configurando {device['name']}: {str(e)}"
