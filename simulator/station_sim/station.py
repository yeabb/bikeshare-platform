"""
Simulates a single station's behavior.

Each Station instance:
- Tracks its dock state (which bike is in which dock)
- Reacts to UNLOCK commands based on its configured behavior mode
- Returns the MQTT events that should be published back

This class has no MQTT knowledge — it just takes a command payload
and returns a list of events to publish. The MQTT layer (main.py) handles
the actual publishing. This makes the behavior easy to unit test.

Behavior modes:
  always_success  - every unlock succeeds, bike undocks and can be re-docked elsewhere
  always_fail     - every unlock fails with the configured failure_reason
  flaky           - succeeds (1 - fail_rate)% of the time, fails otherwise
  slow            - succeeds but waits delay_sec before responding
  timeout         - never publishes UNLOCK_RESULT (simulates offline station)
"""
import logging
import random
import time
from typing import Optional

from station_sim.config import StationConfig

logger = logging.getLogger(__name__)


class Station:
    def __init__(self, config: StationConfig):
        self.config = config
        self.station_id = config.id

        # dock_index → bike_id (or None if empty)
        # Mirrors the DB state — kept in sync as bikes dock/undock
        self.dock_state: dict[int, Optional[str]] = {
            dock.index: dock.bike_id for dock in config.docks
        }

    def handle_unlock_command(self, payload: dict) -> list[dict]:
        """
        Process an UNLOCK command and return a list of MQTT event payloads
        to publish back on station/{station_id}/events.

        Returns an empty list for timeout behavior (no response).

        The caller (main.py) is responsible for publishing these events
        and adding any delays between them.
        """
        request_id = payload["requestId"]
        dock_id = payload["dockId"]
        bike_id = payload["bikeId"]
        ttl_sec = payload.get("ttlSec", 10)

        logger.info(
            f"[{self.station_id}] UNLOCK request={request_id} "
            f"dock={dock_id} bike={bike_id}"
        )

        # --- timeout: station goes silent ---
        if self.config.behavior == "timeout":
            logger.warning(
                f"[{self.station_id}] Simulating timeout — not responding to {request_id}"
            )
            return []

        # --- slow: wait before responding ---
        if self.config.behavior == "slow":
            logger.info(f"[{self.station_id}] Slow mode — waiting {self.config.delay_sec}s")
            time.sleep(self.config.delay_sec)

        # --- verify bike is actually in this dock ---
        actual_bike = self.dock_state.get(dock_id)
        if actual_bike != bike_id:
            logger.warning(
                f"[{self.station_id}] Bike mismatch at dock {dock_id}: "
                f"expected {bike_id}, found {actual_bike}"
            )
            return [self._unlock_result(request_id, dock_id, bike_id, "FAILED", "BIKE_MISMATCH")]

        # --- determine success or failure based on behavior ---
        should_fail = self._should_fail()

        if should_fail:
            logger.info(f"[{self.station_id}] Simulating failure: {self.config.failure_reason}")
            return [
                self._unlock_result(
                    request_id, dock_id, bike_id, "FAILED", self.config.failure_reason
                )
            ]

        # --- success: unlock, bike leaves dock ---
        logger.info(f"[{self.station_id}] Unlock SUCCESS for bike {bike_id} at dock {dock_id}")

        # Update internal dock state — bike is leaving
        self.dock_state[dock_id] = None

        return [
            self._unlock_result(request_id, dock_id, bike_id, "SUCCESS", None),
            self._bike_undocked(dock_id, bike_id),
        ]

    def handle_bike_docked(self, dock_index: int, bike_id: str) -> list[dict]:
        """
        Simulate a bike being physically docked at this station.
        Called externally (e.g. from a scenario script) to end a ride.
        Returns the BIKE_DOCKED event payload to publish.
        """
        self.dock_state[dock_index] = bike_id
        logger.info(f"[{self.station_id}] Bike {bike_id} docked at dock {dock_index}")
        return [self._bike_docked(dock_index, bike_id)]

    def find_available_dock(self) -> Optional[int]:
        """Return the index of an empty dock, or None if all are occupied."""
        for index, bike in self.dock_state.items():
            if bike is None:
                return index
        return None

    # --- private helpers ---

    def _should_fail(self) -> bool:
        if self.config.behavior == "always_fail":
            return True
        if self.config.behavior == "always_success":
            return False
        if self.config.behavior == "flaky":
            return random.random() < self.config.fail_rate
        if self.config.behavior == "slow":
            return False  # slow succeeds, just delayed
        return False

    def _unlock_result(
        self,
        request_id: str,
        dock_id: int,
        bike_id: str,
        status: str,
        reason: Optional[str],
    ) -> dict:
        return {
            "type": "UNLOCK_RESULT",
            "requestId": request_id,
            "stationId": self.station_id,
            "dockId": dock_id,
            "bikeId": bike_id,
            "status": status,
            "reason": reason,
            "ts": _now_ts(),
        }

    def _bike_undocked(self, dock_id: int, bike_id: str) -> dict:
        return {
            "type": "BIKE_UNDOCKED",
            "stationId": self.station_id,
            "dockId": dock_id,
            "bikeId": bike_id,
            "ts": _now_ts(),
        }

    def _bike_docked(self, dock_id: int, bike_id: str) -> dict:
        return {
            "type": "BIKE_DOCKED",
            "stationId": self.station_id,
            "dockId": dock_id,
            "bikeId": bike_id,
            "ts": _now_ts(),
        }


def _now_ts() -> int:
    return int(time.time())
