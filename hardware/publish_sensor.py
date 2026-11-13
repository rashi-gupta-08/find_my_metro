"""Forward an actual device event; never generate train identity, timestamps or position."""
import argparse
import json
import os
import urllib.request
from urllib.parse import urlparse
from pathlib import Path
from backend.app.contracts import SensorEvent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("event_file")
    parser.add_argument("--transport", choices=["http", "mqtt"], default="http")
    parser.add_argument("--api", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    payload = SensorEvent.model_validate_json(Path(args.event_file).read_text(encoding="utf-8-sig")).model_dump(mode="json")
    if args.transport == "http":
        url = args.api.rstrip("/")+"/api/v1/sensor-events"
        parsed = urlparse(url)
        if parsed.scheme != "https" and parsed.hostname not in {"127.0.0.1", "localhost"}:
            raise ValueError("Remote device ingestion requires HTTPS")
        credential = os.environ["METRO_DEVICE_KEY"]
        request = urllib.request.Request(url, data=json.dumps(payload).encode(), headers={"Content-Type":"application/json", "X-API-Key":credential}, method="POST")
        with urllib.request.urlopen(request, timeout=15) as response:
            print(response.read().decode())
    else:
        import paho.mqtt.publish as publish
        publish.single("metro/sensors/"+payload["node_id"]+"/events", payload=json.dumps(payload), qos=1,
                       hostname=os.environ["MQTT_HOST"], port=int(os.environ.get("MQTT_PORT", "8883")),
                       auth={"username":payload["node_id"], "password":os.environ["METRO_MQTT_PASSWORD"]},
                       tls={"ca_certs":os.environ["MQTT_CA_FILE"]})
        print("Event delivered to the broker. Check its event ID in the operator audit after ingestion.")


if __name__ == "__main__":
    main()
