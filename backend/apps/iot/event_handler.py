"""
Handler for incoming MQTT events from stations.

Entry points:
- Local dev:  called directly by the local MQTT subscriber process
- Production: called by the Lambda function after IoT Core rule fires

Usage:
    from apps.iot.event_handler import handle_station_event
    handle_station_event(station_id="S001", payload={...})
"""
import logging

logger = logging.getLogger(__name__)

# Map event type strings to handler functions
_HANDLERS = {}


def handle_station_event(station_id: str, payload: dict) -> None:
    """
    Parse and dispatch a station event to the appropriate service handler.

    Args:
        station_id: Station identifier, e.g. "S001"
        payload: Parsed JSON dict from the MQTT message body
    """
    event_type = payload.get("type")
    handler = _HANDLERS.get(event_type)

    if handler is None:
        logger.warning(f"Unknown event type '{event_type}' from station {station_id}")
        return

    try:
        handler(payload)
    except Exception:
        logger.exception(
            f"Error handling event type='{event_type}' station={station_id}"
        )


def _handle_unlock_result(payload: dict) -> None:
    from apps.commands.services import handle_unlock_result

    handle_unlock_result(
        request_id=payload["requestId"],
        status=payload["status"],
        reason=payload.get("reason"),
    )


def _handle_bike_docked(payload: dict) -> None:
    from apps.rides.services import end_ride_on_dock

    end_ride_on_dock(
        bike_id=payload["bikeId"],
        end_station_id=payload["stationId"],
        end_dock_index=payload["dockId"],
        event_ts=payload["ts"],
    )


def _handle_bike_undocked(payload: dict) -> None:
    from apps.stations.services import handle_bike_undocked

    handle_bike_undocked(
        station_id=payload["stationId"],
        dock_index=payload["dockId"],
        bike_id=payload["bikeId"],
    )


def _handle_dock_fault(payload: dict) -> None:
    from apps.stations.services import handle_dock_fault

    handle_dock_fault(
        station_id=payload["stationId"],
        dock_index=payload["dockId"],
        fault_code=payload.get("faultCode", "UNKNOWN"),
    )


def _handle_dock_fault_cleared(payload: dict) -> None:
    from apps.stations.services import handle_dock_fault_cleared

    handle_dock_fault_cleared(
        station_id=payload["stationId"],
        dock_index=payload["dockId"],
    )


def _handle_telemetry(payload: dict) -> None:
    # TODO: implement telemetry reconciliation against DB state
    logger.info(f"Received telemetry from station {payload.get('stationId')}")


_HANDLERS = {
    "UNLOCK_RESULT": _handle_unlock_result,
    "BIKE_DOCKED": _handle_bike_docked,
    "BIKE_UNDOCKED": _handle_bike_undocked,
    "DOCK_FAULT": _handle_dock_fault,
    "DOCK_FAULT_CLEARED": _handle_dock_fault_cleared,
    "STATION_TELEMETRY": _handle_telemetry,
}
