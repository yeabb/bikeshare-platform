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
"""
import argparse
import json
import logging
import os
import random
import sys
import threading
import time
from pathlib import Path

import paho.mqtt.client as mqtt

# Allow running from simulator/ directory
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from station_sim.config import FleetConfig, StationConfig, UserConfig, load_fleet
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

# How often each station broadcasts its full dock state snapshot.
# Backend uses this to catch missed events and correct DB drift.
TELEMETRY_INTERVAL_SEC = 30


def build_fleet(config: FleetConfig) -> dict[str, Station]:
    """Build a Station instance for each station in the fleet config."""
    return {s.id: Station(s) for s in config.stations}


def build_user_map(config: FleetConfig) -> dict[str, UserConfig]:
    """Build a phone → UserConfig lookup for ride behavior."""
    return {u.phone: u for u in config.users}


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

    If the unlock succeeds, kicks off a background thread to simulate
    the rider's journey and eventual bike return.
    """
    fleet: dict[str, Station] = userdata["fleet"]
    user_map: dict[str, UserConfig] = userdata["user_map"]

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

        # If the unlock succeeded, simulate the rider's journey in a background thread.
        # We check the first event — UNLOCK_RESULT with status SUCCESS.
        unlock_succeeded = (
            events
            and events[0].get("type") == "UNLOCK_RESULT"
            and events[0].get("status") == "SUCCESS"
        )
        if unlock_succeeded:
            user_phone = payload.get("userId")
            bike_id = payload["bikeId"]
            user_config = user_map.get(user_phone)

            if user_config is None:
                logger.warning(
                    f"No behavior config for user {user_phone} — bike {bike_id} will not be returned"
                )
                return

            thread = threading.Thread(
                target=_simulate_ride,
                args=(client, fleet, bike_id, station_id, user_config),
                daemon=True,
            )
            thread.start()
    else:
        logger.warning(f"Unknown command type: {command_type}")


def _simulate_ride(
    client: mqtt.Client,
    fleet: dict[str, Station],
    bike_id: str,
    origin_station_id: str,
    user: UserConfig,
) -> None:
    """
    Runs in a background thread. Simulates a rider's journey after a successful unlock.

    Behavior is driven entirely by the user's profile from fleet.yml:
      commuter   — always rides to the same fixed destination station
      explorer   — picks a random station each time
      indecisive — returns to the same station they left from
      ghost      — high chance of never returning the bike
      tourist    — long ride, random destination

    Steps:
      1. Decide whether the rider returns the bike at all (no_return_rate)
      2. Sleep for a random ride duration within the user's configured range
      3. Pick a destination station based on behavior
      4. Find an available dock at that station
      5. Publish BIKE_DOCKED to close out the ride
    """
    logger.info(
        f"[Ride] {user.phone} ({user.behavior}) — bike {bike_id} left {origin_station_id}"
    )

    # 1. Ghost check — does this rider ever return the bike?
    if random.random() < user.no_return_rate:
        logger.info(
            f"[Ride] {user.phone} ({user.behavior}) — bike {bike_id} not returned (ghost ride)"
        )
        return

    # 2. Sleep for ride duration
    min_sec, max_sec = user.ride_duration_range
    duration = random.uniform(min_sec, max_sec)
    logger.info(
        f"[Ride] {user.phone} ({user.behavior}) — riding for {duration:.0f}s, "
        f"will return bike {bike_id}"
    )
    time.sleep(duration)

    # 3. Pick destination station
    destination_id = _pick_destination(fleet, origin_station_id, user)
    if destination_id is None:
        logger.warning(f"[Ride] No valid destination found for bike {bike_id} — not returned")
        return

    destination = fleet[destination_id]

    # 4. Find an available dock
    dock_index = destination.find_available_dock()
    if dock_index is None:
        logger.warning(
            f"[Ride] No available dock at {destination_id} for bike {bike_id} — not returned"
        )
        return

    # 5. Dock the bike and publish BIKE_DOCKED
    events = destination.handle_bike_docked(dock_index, bike_id)
    _publish_events(client, destination_id, events)
    logger.info(
        f"[Ride] {user.phone} ({user.behavior}) — bike {bike_id} returned to "
        f"{destination_id} dock {dock_index}"
    )


def _pick_destination(
    fleet: dict[str, Station],
    origin_station_id: str,
    user: UserConfig,
) -> str | None:
    """
    Choose a destination station based on the user's behavior profile.

      commuter   — always goes to commuter_destination (fixed in fleet.yml)
      indecisive — returns to the same station they started from
      explorer   — any station in the fleet, chosen at random (could be origin)
      tourist    — same as explorer but the ride duration is longer (handled in fleet.yml)
      ghost      — should never reach here (filtered out before this call)
    """
    if user.behavior == "commuter":
        dest = user.commuter_destination
        if dest not in fleet:
            logger.warning(f"Commuter destination {dest} not in fleet — falling back to random")
            return random.choice(list(fleet.keys()))
        return dest

    if user.behavior == "indecisive":
        return origin_station_id

    # explorer / tourist / fallback: random station from the full fleet
    return random.choice(list(fleet.keys()))


def _telemetry_loop(client: mqtt.Client, fleet: dict[str, Station]) -> None:
    """
    Background thread: publishes STATION_TELEMETRY for every station every
    TELEMETRY_INTERVAL_SEC seconds.

    Builds the snapshot from each Station's in-memory dock_state, which is
    kept in sync as bikes dock and undock during the simulation.
    """
    while True:
        time.sleep(TELEMETRY_INTERVAL_SEC)
        for station_id, station in fleet.items():
            payload = _build_telemetry_payload(station)
            topic = f"station/{station_id}/telemetry"
            client.publish(topic, json.dumps(payload), qos=1)
            logger.debug(f"Telemetry published → {topic}")


def _build_telemetry_payload(station: Station) -> dict:
    """Build the STATION_TELEMETRY payload from the station's current dock state."""
    docks = [
        {
            "dockId": dock_index,
            "state": "OCCUPIED" if bike_id else "AVAILABLE",
            "bikeId": bike_id,
            "healthy": True,
            "faultCode": None,
        }
        for dock_index, bike_id in sorted(station.dock_state.items())
    ]
    return {
        "type": "STATION_TELEMETRY",
        "stationId": station.station_id,
        "ts": int(time.time()),
        "docks": docks,
    }


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


def run(host: str, port: int, fleet: dict[str, Station], user_map: dict[str, UserConfig]):
    client = mqtt.Client(userdata={"fleet": fleet, "user_map": user_map})
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

    telemetry_thread = threading.Thread(
        target=_telemetry_loop,
        args=(client, fleet),
        daemon=True,
        name="telemetry",
    )
    telemetry_thread.start()

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
    user_map = build_user_map(config)

    station_list = ", ".join(f"{s} ({fleet[s].config.behavior})" for s in fleet)
    logger.info(f"Simulating fleet: {station_list}")

    user_list = ", ".join(f"{u.phone} ({u.behavior})" for u in config.users)
    logger.info(f"User profiles: {user_list}")

    run(args.host, args.port, fleet, user_map)


if __name__ == "__main__":
    main()
