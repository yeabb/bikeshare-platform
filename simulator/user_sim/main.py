"""
User Simulator — entry point.

Simulates users making HTTP requests to the bikeshare backend.
Each user authenticates, unlocks a bike, and polls until the command
resolves and the ride ends. The ride lifecycle (BIKE_DOCKED events) is
handled by the station simulator — this just watches the API.

Usage:
    # All users from fleet.yml concurrently (uses bike_id from each user's config)
    python -m user_sim.main

    # Single user with bike override
    python -m user_sim.main --user +15550000001 --bike B001

    # Custom API URL
    python -m user_sim.main --api http://localhost:8000
"""
import argparse
import logging
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from station_sim.config import UserConfig, load_fleet
from user_sim.client import BikeShareClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("user_sim")

FLEET_YML = Path(__file__).resolve().parents[1] / "fleet.yml"

# How often to check command/ride status while polling
POLL_INTERVAL_SEC = 2

# Max seconds to wait for a command to leave PENDING state
COMMAND_POLL_TIMEOUT_SEC = 20

# Max seconds to wait for a ride to end (ghost users may never return)
RIDE_POLL_TIMEOUT_SEC = 120


def simulate_user(phone: str, bike_id: str, base_url: str) -> None:
    """
    Full flow for one user:
      1. Authenticate (request OTP → verify OTP → JWT token)
      2. Unlock a bike
      3. Poll command until SUCCESS / FAILED / TIMEOUT
      4. If SUCCESS, poll active-ride until it ends (or we give up)
    """
    client = BikeShareClient(base_url, phone)

    try:
        # 1. Authenticate
        logger.info(f"[{phone}] Authenticating...")
        client.authenticate()

        # 2. Unlock
        logger.info(f"[{phone}] Unlocking bike {bike_id}...")
        request_id = client.unlock(bike_id)
        logger.info(f"[{phone}] Command submitted → {request_id} (PENDING)")

        # 3. Poll command status
        command = _poll_command_until_terminal(client, phone, request_id)
        status = command.get("status")

        if status != "SUCCESS":
            logger.info(f"[{phone}] Unlock did not succeed (status={status}) — done")
            return

        ride_id = command.get("ride_id")
        logger.info(f"[{phone}] Unlock SUCCESS — ride started → {ride_id}")

        # 4. Wait for ride to end (station_sim publishes BIKE_DOCKED, backend ends the ride)
        _wait_for_ride_end(client, phone, ride_id)

    except Exception as e:
        logger.error(f"[{phone}] Error: {e}")


def _poll_command_until_terminal(
    client: BikeShareClient, phone: str, request_id: str
) -> dict:
    """Poll GET /commands/{request_id} until status is no longer PENDING."""
    deadline = time.monotonic() + COMMAND_POLL_TIMEOUT_SEC
    while time.monotonic() < deadline:
        command = client.poll_command(request_id)
        if command.get("status") != "PENDING":
            return command
        logger.debug(f"[{phone}] Command still PENDING...")
        time.sleep(POLL_INTERVAL_SEC)

    logger.warning(f"[{phone}] Command still PENDING after {COMMAND_POLL_TIMEOUT_SEC}s — giving up")
    return {"status": "UNKNOWN"}


def _wait_for_ride_end(client: BikeShareClient, phone: str, ride_id: str) -> None:
    """Poll GET /me/active-ride until the ride ends (404 = no active ride = completed)."""
    deadline = time.monotonic() + RIDE_POLL_TIMEOUT_SEC
    while time.monotonic() < deadline:
        ride = client.get_active_ride()
        if ride is None:
            logger.info(f"[{phone}] Ride {ride_id} completed")
            return
        time.sleep(POLL_INTERVAL_SEC)

    logger.warning(
        f"[{phone}] Ride {ride_id} still active after {RIDE_POLL_TIMEOUT_SEC}s — "
        "user may be a ghost rider"
    )


def main():
    parser = argparse.ArgumentParser(description="Bikeshare user simulator")
    parser.add_argument(
        "--api", default="http://localhost:8000", help="Backend base URL (default: http://localhost:8000)"
    )
    parser.add_argument(
        "--fleet", default=str(FLEET_YML), help="Path to fleet.yml"
    )
    parser.add_argument(
        "--user", help="Phone number to simulate (default: all users in fleet.yml)"
    )
    parser.add_argument(
        "--bike", help="Bike ID to unlock (overrides bike_id from fleet.yml)"
    )
    args = parser.parse_args()

    config = load_fleet(Path(args.fleet))

    if args.user:
        # Single-user mode
        user_cfg = next((u for u in config.users if u.phone == args.user), None)
        if user_cfg is None:
            logger.error(f"User {args.user} not found in fleet.yml")
            sys.exit(1)
        bike_id = args.bike or user_cfg.bike_id
        if not bike_id:
            logger.error(
                f"No bike specified for {args.user}. "
                "Use --bike BIKE_ID or add bike_id to the user entry in fleet.yml."
            )
            sys.exit(1)
        simulate_user(args.user, bike_id, args.api)

    else:
        # All-users mode — run each user concurrently
        threads = []
        for user in config.users:
            bike_id = args.bike or user.bike_id
            if not bike_id:
                logger.warning(
                    f"[{user.phone}] No bike_id configured — skipping. "
                    "Add bike_id to fleet.yml or pass --bike."
                )
                continue
            t = threading.Thread(
                target=simulate_user,
                args=(user.phone, bike_id, args.api),
                daemon=True,
                name=f"user-{user.phone}",
            )
            threads.append(t)

        if not threads:
            logger.error("No users to simulate.")
            sys.exit(1)

        logger.info(f"Starting {len(threads)} user(s) concurrently...")
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        logger.info("All users done.")


if __name__ == "__main__":
    main()
