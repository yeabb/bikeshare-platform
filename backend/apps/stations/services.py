import logging

from apps.stations.models import Dock, DockState

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
