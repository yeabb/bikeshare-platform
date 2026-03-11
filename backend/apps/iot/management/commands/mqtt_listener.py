"""
Management command: mqtt_listener

Subscribes to station MQTT events from Mosquitto and feeds them into
event_handler.handle_station_event() — exactly what the Lambda does in production.

This command is LOCAL DEV ONLY. In production, AWS IoT Core + Lambda handles
inbound events. This command is the local equivalent.

                Local                          Production
                -----                          ----------
Mosquitto → mqtt_listener (this) →         IoT Core → Lambda →
            event_handler.handle_station_event()

Usage:
    python manage.py mqtt_listener
    python manage.py mqtt_listener --host localhost --port 1883
"""
import json
import logging
import os

import paho.mqtt.client as mqtt
from django.core.management.base import BaseCommand

from apps.iot.event_handler import handle_station_event

logger = logging.getLogger("mqtt_listener")


class Command(BaseCommand):
    help = "Subscribe to station MQTT events and feed them into the event handler (local dev only)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--host",
            default=os.environ.get("MQTT_BROKER_HOST", "localhost"),
            help="MQTT broker host",
        )
        parser.add_argument(
            "--port",
            type=int,
            default=int(os.environ.get("MQTT_BROKER_PORT", "1883")),
            help="MQTT broker port",
        )

    def handle(self, *args, **options):
        host = options["host"]
        port = options["port"]

        self.stdout.write(f"Connecting to MQTT broker at {host}:{port}")

        client = mqtt.Client()
        client.on_connect = self._on_connect
        client.on_message = self._on_message

        # AWS IoT Core note:
        # In production this is replaced by IoT Core + Lambda.
        # If you ever want to point this listener at IoT Core for testing:
        #   client.tls_set(ca_certs, certfile, keyfile)
        #   client.connect(AWS_IOT_ENDPOINT, port=8883)

        client.connect(host, port, keepalive=60)

        self.stdout.write(self.style.SUCCESS("MQTT listener running. Ctrl+C to stop."))

        try:
            client.loop_forever()
        except KeyboardInterrupt:
            self.stdout.write("Shutting down MQTT listener")
            client.disconnect()

    def _on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            # Two subscriptions mirror the two IoT Rules used in production:
            # Rule 1: station/+/events    → event ingestion Lambda
            # Rule 2: station/+/telemetry → same Lambda (separate rule so each
            #         can have independent retry/error policies in production)
            client.subscribe("station/+/events", qos=1)
            client.subscribe("station/+/telemetry", qos=1)
            logger.info("Subscribed to station/+/events and station/+/telemetry")
        else:
            logger.error(f"MQTT connection failed with code {rc}")

    def _on_message(self, client, userdata, msg):
        """
        Called for every event published by a station (or simulator).
        Parses the topic to get station_id, parses the payload, and
        calls the same event_handler that the Lambda calls in production.
        """
        try:
            payload = json.loads(msg.payload.decode())
        except json.JSONDecodeError:
            logger.error(f"Invalid JSON on {msg.topic}: {msg.payload}")
            return

        # Topic format: station/{station_id}/events
        parts = msg.topic.split("/")
        if len(parts) != 3:
            logger.error(f"Unexpected topic format: {msg.topic}")
            return

        station_id = parts[1]
        event_type = payload.get("type", "UNKNOWN")

        logger.info(f"← {msg.topic}: {event_type}")

        try:
            handle_station_event(station_id, payload)
        except Exception:
            logger.exception(
                f"Unhandled error processing event type={event_type} station={station_id}"
            )
