import logging
from datetime import datetime
from datetime import timezone as dt_timezone

from django.db import transaction
from django.utils import timezone

from apps.stations.models import Dock, DockState, Station, StationStatus

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


def reconcile_telemetry(station_id: str, docks_snapshot: list[dict], telemetry_ts: int = None) -> None:
    """
    Safety-net reconciliation triggered by periodic STATION_TELEMETRY events.

    Compares each dock's physical state (from the station's hardware snapshot)
    against the DB and corrects any drift caused by missed events.

    Rules:
    - Telemetry wins for dock state and bike presence
    - UNLOCKING docks are skipped — the command TTL sweep owns that window
    - Rides require two consecutive snapshots to end (two-snapshot confirmation):
        First snapshot:  sets ride.suspected_return_at to the telemetry timestamp
        Second snapshot: confirmed — ends the ride using suspected_return_at as
                         ended_at so billing reflects when the bike actually docked
    - Bike mismatches (wrong bike in dock) are logged but not auto-corrected

    Called every 30s per station. Must be a no-op when states already agree.
    """
    snapshot_time = (
        datetime.fromtimestamp(telemetry_ts, tz=dt_timezone.utc)
        if telemetry_ts
        else timezone.now()
    )
    with transaction.atomic():
        # Update last_telemetry_at every time we hear from this station.
        # If the station was INACTIVE (flagged as down), restore it to ACTIVE now
        # that it's reporting again.
        try:
            station = Station.objects.get(id=station_id)
            if station.status == StationStatus.INACTIVE:
                station.status = StationStatus.ACTIVE
                logger.info(f"Station {station_id} is back online — restored to ACTIVE")
            station.last_telemetry_at = timezone.now()
            station.save(update_fields=["last_telemetry_at", "status", "updated_at"])
        except Station.DoesNotExist:
            logger.warning(f"Telemetry received for unknown station {station_id} — skipping")
            return

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
                    # States match — but the bike may have a suspected return from a
                    # previous snapshot. If so, this is the second confirmation: end the ride.
                    if dock.current_bike:
                        _handle_potential_stale_ride(dock.current_bike, station_id, dock, snapshot_time)
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
                departed_bike = dock.current_bike
                departed_bike_id = dock.current_bike_id
                dock.state = DockState.AVAILABLE
                dock.current_bike = None
                dock.save(update_fields=["state", "current_bike", "updated_at"])

                # If we had flagged a suspected return for this bike, clear it —
                # the bike left again before the second snapshot confirmed the return.
                if departed_bike:
                    from apps.rides.models import Ride, RideStatus
                    cleared = Ride.objects.filter(
                        bike=departed_bike,
                        status=RideStatus.ACTIVE,
                        suspected_return_at__isnull=False,
                    ).update(suspected_return_at=None)
                    if cleared:
                        logger.info(
                            f"Cleared suspected_return_at for active ride — "
                            f"bike {departed_bike_id} departed before second-snapshot confirmation"
                        )

                logger.warning(
                    f"Telemetry: {dock.display_id} corrected OCCUPIED→AVAILABLE "
                    f"(bike {departed_bike_id} departed) — missed BIKE_UNDOCKED event"
                )
                continue

            # AVAILABLE → OCCUPIED: missed BIKE_DOCKED event.
            # Fix dock state and start the two-snapshot confirmation clock.
            # If the bike is still here next snapshot, end the stale ride.
            if dock.state == DockState.AVAILABLE and tel_state == "OCCUPIED":
                bike = _resolve_bike(tel_bike_id, dock.display_id)
                dock.state = DockState.OCCUPIED
                dock.current_bike = bike
                dock.save(update_fields=["state", "current_bike", "updated_at"])
                if bike:
                    _sync_bike_location(bike, station_id, dock)
                    _handle_potential_stale_ride(bike, station_id, dock, snapshot_time)
                logger.warning(
                    f"Telemetry: {dock.display_id} corrected AVAILABLE→OCCUPIED (bike {tel_bike_id}) — "
                    "missed BIKE_DOCKED event"
                )
                continue


def station_heartbeat_check() -> int:
    """
    Checks all ACTIVE stations for signs of life. Marks any silent station INACTIVE.

    A station is considered silent if:
    - last_telemetry_at is older than TELEMETRY_TIMEOUT_SEC (90s — 3 missed reports), OR
    - last_telemetry_at is null AND the station was created more than
      STATION_GRACE_PERIOD_SEC (5 min) ago — gives new stations time to come online

    Called every 60s by:
    - Local: station_heartbeat management command (Procfile)
    - Production: CloudWatch Scheduled Rule → Lambda

    Returns the number of stations marked INACTIVE.
    """
    TELEMETRY_TIMEOUT_SEC = 90
    STATION_GRACE_PERIOD_SEC = 300  # 5 minutes

    now = timezone.now()
    stale_cutoff = now - timezone.timedelta(seconds=TELEMETRY_TIMEOUT_SEC)
    grace_cutoff = now - timezone.timedelta(seconds=STATION_GRACE_PERIOD_SEC)

    stations = Station.objects.filter(status=StationStatus.ACTIVE)
    count = 0

    for station in stations:
        is_stale = (
            station.last_telemetry_at is not None
            and station.last_telemetry_at < stale_cutoff
        )
        is_never_reported_past_grace = (
            station.last_telemetry_at is None
            and station.created_at < grace_cutoff
        )

        if is_stale or is_never_reported_past_grace:
            station.status = StationStatus.INACTIVE
            station.save(update_fields=["status", "updated_at"])
            logger.warning(
                f"Station {station.id} ({station.name}) marked INACTIVE — "
                f"last telemetry: {station.last_telemetry_at or 'never'}"
            )
            count += 1

    return count


def _handle_potential_stale_ride(bike, station_id: str, dock, snapshot_time) -> None:
    """
    Two-snapshot stale ride reconciliation.

    When telemetry shows a dock OCCUPIED with a bike that has an active ride but
    no BIKE_DOCKED event was received, we require two consecutive snapshots (~30s
    apart) before ending the ride to avoid false positives.

    First snapshot:  sets ride.suspected_return_at to the telemetry timestamp.
    Second snapshot: confirmed — ends the ride using suspected_return_at as ended_at
                     so billing reflects when the bike first appeared docked, not now.
    """
    from apps.rides.models import Ride, RideStatus

    try:
        ride = Ride.objects.get(bike=bike, status=RideStatus.ACTIVE)
    except Ride.DoesNotExist:
        return  # No active ride for this bike — nothing to do

    if ride.suspected_return_at is None:
        # First sighting — record the suspected return time
        ride.suspected_return_at = snapshot_time
        ride.save(update_fields=["suspected_return_at", "updated_at"])
        logger.warning(
            f"Stale ride {ride.ride_id} — suspected return detected. "
            f"bike={bike.id} dock={dock.display_id}. "
            "Will confirm on next telemetry snapshot (~30s)."
        )
    else:
        # Second sighting — confirmed. End the ride using the first snapshot time.
        logger.warning(
            f"Stale ride {ride.ride_id} confirmed — ending ride. "
            f"ended_at={ride.suspected_return_at} (first snapshot timestamp)"
        )
        from apps.rides.services import end_ride_on_dock
        end_ride_on_dock(
            bike_id=bike.id,
            end_station_id=station_id,
            end_dock_index=dock.dock_index,
            event_ts=int(snapshot_time.timestamp()),
            ended_at=ride.suspected_return_at,
        )


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
