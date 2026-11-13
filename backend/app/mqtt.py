import json
import logging
import paho.mqtt.client as mqtt
from .acquisition import ingest
from .config import settings
from .db import transaction
from .models import Device

log = logging.getLogger(__name__)


def main():
    if not settings.mqtt_enabled:
        raise RuntimeError("MQTT is disabled; provision a TLS broker and device ACLs before enabling it")
    logging.basicConfig(level=logging.INFO)
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="metro-durable-ingestor", clean_session=False, manual_ack=True)
    client.username_pw_set(settings.mqtt_user, settings.mqtt_password)
    if settings.mqtt_ca_file:
        client.tls_set(ca_certs=settings.mqtt_ca_file)
    client.reconnect_delay_set(min_delay=1, max_delay=30)

    def connected(client, userdata, flags, reason_code, properties):
        if reason_code == 0:
            client.subscribe("metro/sensors/+/events", qos=1)
            log.info("MQTT acquisition connected")

    def message(client, userdata, message):
        try:
            try:
                raw = json.loads(message.payload)
            except (ValueError, UnicodeDecodeError):
                raw = {"malformed_json": message.payload[:4000].decode("utf-8", errors="replace")}
            if not isinstance(raw, dict):
                raw = {"invalid_value": raw}
            topic_node = message.topic.split("/")[2]
            if raw.get("node_id") != topic_node:
                raw["topic_node_mismatch"] = True
            with transaction() as session:
                device = session.get(Device, topic_node)
                if not device or device.disabled:
                    raw["unregistered_device"] = True
                if len(message.payload) > settings.max_request_bytes:
                    raw = {"oversized_message": True}
                ingest(session, raw, "wsn")
            if message.qos:
                client.ack(message.mid, message.qos)
        except Exception as error:
            log.error("MQTT event could not be durably stored; withholding acknowledgement (%s)", type(error).__name__)
            client.disconnect()

    client.on_connect, client.on_message = connected, message
    client.connect(settings.mqtt_host, settings.mqtt_port, keepalive=30)
    client.loop_forever(retry_first_connection=True)


if __name__ == "__main__":
    main()
