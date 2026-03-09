"""
Station Simulator — entry point.

Connects to an MQTT broker and simulates a fleet of stations.

Local dev:  connects to Mosquitto (no TLS, no auth)
Production: each real station connects to AWS IoT Core with its own TLS
            certificate. The simulator is NOT used in production — real
            hardware replaces it. But if you ever want to run the simulator
            against IoT Core for testing, pass --broker-type=aws and set
            AWS_IOT_ENDPOINT + cert paths via env vars.

Usage:
    # Local (Mosquitto)
    python -m station_sim.main

    # Override broker host (e.g. if running outside Docker)
    python -m station_sim.main --host localhost --port 1883

    # Simulate a single specific scenario then exit
    python -m station_sim.main --scenario cross_station_ride
"""
import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path

import paho.mqtt.client as mqtt

# Allow running from simulator/ directory
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from station_sim.config import FleetConfig, StationConfig, load_fleet
from station_sim.station import Station

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("station_sim")

FLEET_YML = Path(__file__).resolve().parents[1] / "fleet.yml"

# Small delay between publishing UNLOCK_RESULT and BIKE_UNDOCKED events.
# Mimics the real-world gap between latch releasing and bike physically departing.
UNDOCK_DELAY_SEC = 1.5


def build_fleet(config: FleetConfig) -> dict[str, Station]:
    """Build a Station instance for each station in the fleet config."""
    return {s.id: Station(s) for s in config.stations}


def on_connect(client, userdata, flags, rc):
    if rc == 0:
        logger.info("Connected to MQTT broker")
        # Subscribe to commands for ALL stations
        # In production: each real station subscribes only to its own topic
        # using its IoT Core certificate's policy. Here we subscribe to all
        # with a wildcard since we're simulating the entire fleet.
        client.subscribe("station/+/cmd", qos=1)
        logger.info("Subscribed to station/+/cmd")
    else:
        logger.error(f"Connection failed with code {rc}")


def on_message(client, userdata, msg):
    """
    Called when a command arrives on station/{station_id}/cmd.

    Parses the topic to identify which station it's for, hands off to
    the Station instance, then publishes each returned event back.
    """
    fleet: dict[str, Station] = userdata["fleet"]

    try:
        payload = json.loads(msg.payload.decode())
    except json.JSONDecodeError:
        logger.error(f"Invalid JSON on topic {msg.topic}: {msg.payload}")
        return

    # Extract station_id from topic: station/{station_id}/cmd
    parts = msg.topic.split("/")
    if len(parts) != 3:
        logger.error(f"Unexpected topic format: {msg.topic}")
        return

    station_id = parts[1]
    station = fleet.get(station_id)

    if station is None:
        logger.warning(f"Received command for unknown station {station_id} — ignoring")
        return

    command_type = payload.get("type")

    if command_type == "UNLOCK":
        events = station.handle_unlock_command(payload)
        _publish_events(client, station_id, events)
    else:
        logger.warning(f"Unknown command type: {command_type}")


def _publish_events(client, station_id: str, events: list[dict]):
    """
    Publish a list of events to station/{station_id}/events.

    We add a small delay between events to mimic real hardware timing.
    For example: UNLOCK_RESULT is published first, then BIKE_UNDOCKED
    a couple of seconds later after the bike physically leaves the dock.
    """
    topic = f"station/{station_id}/events"

    for i, event in enumerate(events):
        if i > 0:
            # Small gap between consecutive events (e.g. UNLOCK_RESULT → BIKE_UNDOCKED)
            time.sleep(UNDOCK_DELAY_SEC)

        payload = json.dumps(event)
        client.publish(topic, payload, qos=1)
        logger.info(f"Published → {topic}: {event['type']}")


def run(host: str, port: int, fleet: dict[str, Station]):
    client = mqtt.Client(userdata={"fleet": fleet})
    client.on_connect = on_connect
    client.on_message = on_message

    # AWS IoT Core note:
    # In production, real stations connect with TLS client certificates:
    #   client.tls_set(ca_certs, certfile, keyfile)
    #   client.connect(AWS_IOT_ENDPOINT, port=8883)
    # The simulator skips this since Mosquitto runs without TLS locally.
    # If you want to test the simulator against IoT Core, add TLS config here.

    logger.info(f"Connecting to broker at {host}:{port}")
    client.connect(host, port, keepalive=60)

    try:
        client.loop_forever()
    except KeyboardInterrupt:
        logger.info("Simulator shutting down")
        client.disconnect()


def main():
    parser = argparse.ArgumentParser(description="Bikeshare station simulator")
    parser.add_argument("--host", default=os.environ.get("MQTT_BROKER_HOST", "localhost"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("MQTT_BROKER_PORT", "1883")))
    parser.add_argument("--fleet", default=str(FLEET_YML), help="Path to fleet.yml")
    args = parser.parse_args()

    config = load_fleet(Path(args.fleet))
    fleet = build_fleet(config)

    station_list = ", ".join(f"{s} ({fleet[s].config.behavior})" for s in fleet)
    logger.info(f"Simulating fleet: {station_list}")

    run(args.host, args.port, fleet)


if __name__ == "__main__":
    main()
