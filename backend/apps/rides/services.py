import logging

from django.db import transaction
from django.utils import timezone

from apps.bikes.models import BikeStatus
from apps.rides.models import Ride, RideStatus
from apps.stations.models import DockState

logger = logging.getLogger(__name__)


def start_ride(command) -> Ride:
    """
    Create an ACTIVE ride for a successful unlock command.
    Must be called inside a transaction (from handle_unlock_result).
    """
    now = timezone.now()

    ride = Ride.objects.create(
        user=command.user,
        bike=command.bike,
        unlock_command=command,
        start_station=command.station,
        start_dock=command.dock,
        started_at=now,
        status=RideStatus.ACTIVE,
    )

    bike = command.bike
    bike.status = BikeStatus.IN_USE
    bike.current_ride = ride
    bike.save(update_fields=["status", "current_ride", "updated_at"])

    logger.info(
        f"Ride {ride.ride_id} ACTIVE — user={command.user_id} bike={command.bike_id}"
    )
    return ride


def end_ride_on_dock(
    bike_id: str, end_station_id: str, end_dock_index: int, event_ts: int,
    ended_at=None,
) -> None:
    """
    End the active ride for a bike when it physically docks.
    Idempotent: safe to call multiple times with the same event.

    Args:
        bike_id: e.g. "B742"
        end_station_id: e.g. "S001"
        end_dock_index: integer dock index from MQTT event (dockId field)
        event_ts: unix timestamp from the triggering event (for logging)
        ended_at: explicit end time to use instead of now(). Passed by telemetry
                  reconciliation so billing reflects the first snapshot timestamp,
                  not the time of second-snapshot confirmation.
    """
    from apps.bikes.models import Bike
    from apps.stations.models import Dock

    try:
        bike = Bike.objects.select_related("current_ride").get(id=bike_id)
    except Bike.DoesNotExist:
        logger.warning(f"BIKE_DOCKED for unknown bike {bike_id}")
        return

    if not bike.current_ride or bike.current_ride.status != RideStatus.ACTIVE:
        logger.info(f"BIKE_DOCKED for bike {bike_id} — no active ride, ignoring (idempotent)")
        return

    try:
        end_dock = Dock.objects.select_related("station").get(
            station_id=end_station_id, dock_index=end_dock_index
        )
        end_station = end_dock.station
    except Dock.DoesNotExist:
        logger.error(
            f"BIKE_DOCKED — unknown dock station={end_station_id} dock_index={end_dock_index}. "
            f"Ending ride without end location."
        )
        end_dock = None
        end_station = None

    resolved_ended_at = ended_at or timezone.now()

    with transaction.atomic():
        ride = bike.current_ride
        ride.status = RideStatus.COMPLETED
        ride.ended_at = resolved_ended_at
        ride.suspected_return_at = None
        ride.end_station = end_station
        ride.end_dock = end_dock
        ride.save(update_fields=["status", "ended_at", "suspected_return_at", "end_station", "end_dock", "updated_at"])

        bike.status = BikeStatus.AVAILABLE
        bike.current_ride = None
        bike.current_station = end_station
        bike.current_dock = end_dock
        bike.save(
            update_fields=[
                "status", "current_ride", "current_station", "current_dock", "updated_at"
            ]
        )

        if end_dock:
            end_dock.state = DockState.OCCUPIED
            end_dock.current_bike = bike
            end_dock.save(update_fields=["state", "current_bike", "updated_at"])

    duration = int((resolved_ended_at - ride.started_at).total_seconds())
    logger.info(
        f"Ride {ride.ride_id} COMPLETED — bike={bike_id} "
        f"end={end_station_id}-{end_dock_index} duration={duration}s"
    )
