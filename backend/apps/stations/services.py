import logging

from django.db import transaction

from apps.stations.models import Dock, DockState, Station

logger = logging.getLogger(__name__)


def handle_bike_undocked(station_id: str, dock_index: int, bike_id: str) -> None:
    """Mark dock as AVAILABLE when a bike physically departs. Idempotent."""
    try:
        dock = Dock.objects.get(station_id=station_id, dock_index=dock_index)
    except Dock.DoesNotExist:
        logger.warning(f"BIKE_UNDOCKED for unknown dock {station_id} dock_index={dock_index}")
        return

    if dock.state == DockState.AVAILABLE:
        return  # Already correct, no-op

    dock.state = DockState.AVAILABLE
    dock.current_bike = None
    dock.save(update_fields=["state", "current_bike", "updated_at"])
    logger.info(f"Dock {dock.display_id} → AVAILABLE (bike {bike_id} departed)")


def handle_dock_fault(station_id: str, dock_index: int, fault_code: str) -> None:
    """Mark dock as FAULT."""
    try:
        dock = Dock.objects.get(station_id=station_id, dock_index=dock_index)
    except Dock.DoesNotExist:
        logger.warning(f"DOCK_FAULT for unknown dock {station_id} dock_index={dock_index}")
        return

    dock.state = DockState.FAULT
    dock.fault_code = fault_code
    dock.save(update_fields=["state", "fault_code", "updated_at"])
    logger.warning(f"Dock {dock.display_id} → FAULT ({fault_code})")


def reconcile_telemetry(station_id: str, docks_snapshot: list[dict]) -> None:
    """
    Safety-net reconciliation triggered by periodic STATION_TELEMETRY events.

    Compares each dock's physical state (from the station's hardware snapshot)
    against the DB and corrects any drift caused by missed events.

    Rules:
    - Telemetry wins for dock state and bike presence
    - UNLOCKING docks are skipped — the command TTL sweep owns that window
    - Rides are never started or ended from telemetry — only explicit events do that
    - Bike mismatches (wrong bike in dock) are logged but not auto-corrected

    Called every 30s per station. Must be a no-op when states already agree.
    """
    with transaction.atomic():
        for snap in docks_snapshot:
            dock_index = snap["dockId"]
            tel_state = snap["state"]       # OCCUPIED | AVAILABLE | UNLOCKING | FAULT
            tel_bike_id = snap.get("bikeId")
            tel_fault_code = snap.get("faultCode") or ""

            try:
                dock = Dock.objects.select_related("current_bike").get(
                    station_id=station_id, dock_index=dock_index
                )
            except Dock.DoesNotExist:
                logger.warning(
                    f"Telemetry: unknown dock {station_id}/{dock_index} — skipping"
                )
                continue

            # UNLOCKING is a transient state owned by the command TTL sweep.
            # Telemetry fires every 30s; the TTL is 10s. By the time telemetry
            # arrives, the sweep has already resolved the UNLOCKING dock.
            if dock.state == DockState.UNLOCKING:
                continue

            # A station should never report UNLOCKING to us — that state is
            # internal to the backend. Ignore and log.
            if tel_state == "UNLOCKING":
                logger.warning(
                    f"Telemetry: {dock.display_id} reports UNLOCKING (DB={dock.state}) — skipping"
                )
                continue

            # --- No-op: already in sync ---

            if dock.state == DockState.AVAILABLE and tel_state == "AVAILABLE":
                continue

            if dock.state == DockState.OCCUPIED and tel_state == "OCCUPIED":
                if dock.current_bike_id == tel_bike_id:
                    continue
                # Bike mismatch — sensor says different bike than DB. Don't auto-correct;
                # the root cause is ambiguous (sensor error vs. manual swap).
                logger.warning(
                    f"Telemetry: {dock.display_id} bike mismatch — "
                    f"DB={dock.current_bike_id}, telemetry={tel_bike_id}. "
                    "Manual investigation required."
                )
                continue

            if dock.state == DockState.FAULT and tel_state == "FAULT":
                if dock.fault_code == tel_fault_code:
                    continue
                dock.fault_code = tel_fault_code
                dock.save(update_fields=["fault_code", "updated_at"])
                logger.warning(
                    f"Telemetry: {dock.display_id} fault code updated → {tel_fault_code}"
                )
                continue

            # --- Corrections ---

            # Any state → FAULT: missed DOCK_FAULT event
            if tel_state == "FAULT":
                dock.state = DockState.FAULT
                dock.fault_code = tel_fault_code
                dock.save(update_fields=["state", "fault_code", "updated_at"])
                logger.warning(
                    f"Telemetry: {dock.display_id} corrected → FAULT ({tel_fault_code}) "
                    f"[was {dock.state}] — missed DOCK_FAULT event"
                )
                continue

            # FAULT → OCCUPIED or AVAILABLE: missed DOCK_FAULT_CLEARED event
            if dock.state == DockState.FAULT:
                if tel_state == "OCCUPIED":
                    bike = _resolve_bike(tel_bike_id, dock.display_id)
                    dock.state = DockState.OCCUPIED
                    dock.fault_code = ""
                    dock.current_bike = bike
                    dock.save(update_fields=["state", "fault_code", "current_bike", "updated_at"])
                    if bike:
                        _sync_bike_location(bike, station_id, dock)
                    logger.warning(
                        f"Telemetry: {dock.display_id} fault cleared → OCCUPIED ({tel_bike_id}) — "
                        "missed DOCK_FAULT_CLEARED event"
                    )
                else:  # AVAILABLE
                    dock.state = DockState.AVAILABLE
                    dock.fault_code = ""
                    dock.current_bike = None
                    dock.save(update_fields=["state", "fault_code", "current_bike", "updated_at"])
                    logger.warning(
                        f"Telemetry: {dock.display_id} fault cleared → AVAILABLE — "
                        "missed DOCK_FAULT_CLEARED event"
                    )
                continue

            # OCCUPIED → AVAILABLE: missed BIKE_UNDOCKED event
            if dock.state == DockState.OCCUPIED and tel_state == "AVAILABLE":
                departed_bike_id = dock.current_bike_id
                dock.state = DockState.AVAILABLE
                dock.current_bike = None
                dock.save(update_fields=["state", "current_bike", "updated_at"])
                logger.warning(
                    f"Telemetry: {dock.display_id} corrected OCCUPIED→AVAILABLE "
                    f"(bike {departed_bike_id} departed) — missed BIKE_UNDOCKED event"
                )
                continue

            # AVAILABLE → OCCUPIED: missed BIKE_DOCKED event.
            # We fix dock state but do NOT end the active ride — that requires an
            # explicit BIKE_DOCKED event. Log clearly so ops can investigate.
            if dock.state == DockState.AVAILABLE and tel_state == "OCCUPIED":
                bike = _resolve_bike(tel_bike_id, dock.display_id)
                dock.state = DockState.OCCUPIED
                dock.current_bike = bike
                dock.save(update_fields=["state", "current_bike", "updated_at"])
                if bike:
                    _sync_bike_location(bike, station_id, dock)
                logger.warning(
                    f"Telemetry: {dock.display_id} corrected AVAILABLE→OCCUPIED (bike {tel_bike_id}) — "
                    "missed BIKE_DOCKED event. Active ride NOT ended — manual resolution required."
                )
                continue


def _resolve_bike(bike_id: str | None, display_id: str):
    """Look up a Bike by ID. Returns None if not found or no ID given."""
    if not bike_id:
        return None
    from apps.bikes.models import Bike
    try:
        return Bike.objects.get(id=bike_id)
    except Bike.DoesNotExist:
        logger.warning(f"Telemetry: {display_id} references unknown bike {bike_id}")
        return None


def _sync_bike_location(bike, station_id: str, dock) -> None:
    """Update Bike.current_station and current_dock to reflect physical location from telemetry."""
    try:
        station = Station.objects.get(id=station_id)
    except Station.DoesNotExist:
        return
    bike.current_station = station
    bike.current_dock = dock
    bike.save(update_fields=["current_station", "current_dock", "updated_at"])


def handle_dock_fault_cleared(station_id: str, dock_index: int) -> None:
    """Restore dock state after fault is cleared. State is derived from bike presence."""
    try:
        dock = Dock.objects.select_related("current_bike").get(
            station_id=station_id, dock_index=dock_index
        )
    except Dock.DoesNotExist:
        logger.warning(
            f"DOCK_FAULT_CLEARED for unknown dock {station_id} dock_index={dock_index}"
        )
        return

    dock.state = DockState.OCCUPIED if dock.current_bike_id else DockState.AVAILABLE
    dock.fault_code = ""
    dock.save(update_fields=["state", "fault_code", "updated_at"])
    logger.info(f"Dock {dock.display_id} fault cleared → {dock.state}")
