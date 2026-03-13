"""
Lambda: Event Ingestion

Triggered by two AWS IoT Core Rules:
  Rule 1: SELECT *, topic(2) AS station_id FROM 'station/+/events'
  Rule 2: SELECT *, topic(2) AS station_id FROM 'station/+/telemetry'

topic(2) extracts the station ID from the middle segment of the topic,
e.g. 'station/S001/events' → station_id = 'S001'.

The Lambda forwards the event to the Django internal endpoint, which
calls handle_station_event() — the same function the local mqtt_listener
calls in dev.

                Local                              Production
                -----                              ----------
  Mosquitto → mqtt_listener → handle_station_event()
                                                   IoT Core → Lambda (this)
                                                       → POST /internal/station-event/
                                                       → handle_station_event()

Environment variables required:
  DJANGO_INTERNAL_URL   Full URL to the internal endpoint, e.g.
                        http://internal-alb.bikeshare.internal/internal/station-event/
  INTERNAL_API_SECRET   Shared secret — must match INTERNAL_API_SECRET in Django settings.
"""
import json
import logging
import os
import urllib.error
import urllib.request

logger = logging.getLogger()
logger.setLevel(logging.INFO)

DJANGO_INTERNAL_URL = os.environ["DJANGO_INTERNAL_URL"]
INTERNAL_API_SECRET = os.environ["INTERNAL_API_SECRET"]


def handler(event, context):
    """
    Entry point for AWS Lambda.

    Args:
        event: Dict containing the MQTT payload fields plus 'station_id'
               injected by the IoT Rule SQL (topic(2)).
        context: Lambda context object (unused).
    """
    station_id = event.get("station_id")
    if not station_id:
        logger.error(f"Missing station_id in event: {event}")
        # Returning without raising — bad events shouldn't block the Rule's
        # error action. Log and discard.
        return {"statusCode": 400, "body": "Missing station_id"}

    event_type = event.get("type", "UNKNOWN")
    logger.info(f"Received event: station={station_id} type={event_type}")

    # Strip the station_id key injected by the IoT Rule before forwarding —
    # it's not part of the original MQTT payload.
    payload = {k: v for k, v in event.items() if k != "station_id"}

    body = json.dumps({"station_id": station_id, "payload": payload}).encode()

    req = urllib.request.Request(
        DJANGO_INTERNAL_URL,
        data=body,
        headers={
            "Content-Type": "application/json",
            "X-Internal-Secret": INTERNAL_API_SECRET,
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            logger.info(
                f"Forwarded: station={station_id} type={event_type} status={resp.status}"
            )
            return {"statusCode": resp.status}
    except urllib.error.HTTPError as e:
        logger.error(f"Django returned {e.code}: {e.read().decode()}")
        raise
    except Exception as e:
        logger.error(f"Failed to forward event to Django: {e}")
        raise
