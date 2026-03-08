import logging

from django.db import transaction
from django.utils import timezone

from apps.bikes.models import Bike, BikeStatus
from apps.commands.models import Command, CommandStatus
from apps.stations.models import DockState

logger = logging.getLogger(__name__)


def create_unlock_command(user, bike_id: str):
    """
    Validate and create a PENDING unlock command, then publish it to MQTT.

    Returns (command, None) on success.
    Returns (None, error_code) on failure.

    Checks (in order):
    1. No active ride for user
    2. No pending command for user
    3. Bike exists and is AVAILABLE
    4. Bike has a known dock in OCCUPIED state
    """
    from apps.iot.publisher import publish_unlock_command

    # Guard: active ride
    if user.rides.filter(status="ACTIVE").exists():
        return None, "ACTIVE_RIDE_EXISTS"

    # Guard: pending command already in flight
    if user.commands.filter(status=CommandStatus.PENDING).exists():
        return None, "PENDING_COMMAND_EXISTS"

    # Lookup bike
    try:
        bike = Bike.objects.select_related("current_dock__station").get(id=bike_id)
    except Bike.DoesNotExist:
        return None, "BIKE_NOT_FOUND"

    if bike.status != BikeStatus.AVAILABLE:
        return None, "BIKE_NOT_AVAILABLE"

    dock = bike.current_dock
    if dock is None:
        return None, "BIKE_NOT_DOCKED"

    if dock.state != DockState.OCCUPIED:
        return None, "DOCK_NOT_OCCUPIED"

    station = dock.station

    with transaction.atomic():
        command = Command.objects.create(
            user=user,
            station=station,
            dock=dock,
            bike=bike,
            status=CommandStatus.PENDING,
            expires_at=timezone.now() + timezone.timedelta(
                seconds=_get_ttl_seconds()
            ),
        )
        # Transition dock to UNLOCKING inside the transaction
        dock.state = DockState.UNLOCKING
        dock.save(update_fields=["state", "updated_at"])

    # Publish outside the transaction — if this fails the command stays PENDING
    # and will eventually be swept to TIMEOUT by the background job.
    try:
        published_at = publish_unlock_command(command)
        command.published_at = published_at
        command.save(update_fields=["published_at"])
    except Exception:
        logger.exception(f"Failed to publish MQTT command for request_id={command.request_id}")

    return command, None


def handle_unlock_result(request_id: str, status: str, reason: str = None) -> None:
    """
    Process an UNLOCK_RESULT event from a station.

    Idempotent: silently ignores if command is already resolved.

    Args:
        request_id: UUID string matching Command.request_id
        status: "SUCCESS" or "FAILED"
        reason: failure reason string, or None on success
    """
    from apps.rides.services import start_ride

    try:
        command = Command.objects.select_related(
            "bike", "station", "dock", "user"
        ).get(request_id=request_id)
    except Command.DoesNotExist:
        logger.warning(f"UNLOCK_RESULT for unknown request_id={request_id}")
        return

    if command.status != CommandStatus.PENDING:
        # Already resolved — duplicate event, safe to ignore
        logger.info(
            f"UNLOCK_RESULT for already-resolved command {request_id} "
            f"(current status={command.status}), ignoring"
        )
        return

    now = timezone.now()

    with transaction.atomic():
        if status == "SUCCESS":
            command.status = CommandStatus.SUCCESS
            command.resolved_at = now
            command.save(update_fields=["status", "resolved_at", "updated_at"])
            start_ride(command)
        else:
            command.status = CommandStatus.FAILED
            command.failure_reason = reason or ""
            command.resolved_at = now
            command.save(update_fields=["status", "failure_reason", "resolved_at", "updated_at"])
            # Restore dock to OCCUPIED
            dock = command.dock
            dock.state = DockState.OCCUPIED
            dock.save(update_fields=["state", "updated_at"])
            logger.info(
                f"Command {request_id} FAILED (reason={reason}). Dock {dock.display_id} → OCCUPIED"
            )


def _get_ttl_seconds() -> int:
    from django.conf import settings
    return getattr(settings, "COMMAND_TTL_SECONDS", 10)
