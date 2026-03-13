"""
Lambda: Station Heartbeat

Triggered by a CloudWatch Scheduled Rule every 60 seconds.

Calls the Django internal heartbeat endpoint, which finds all ACTIVE stations
that have not sent telemetry within the inactivity threshold and marks them
INACTIVE. Operations staff can then see which stations need attention via
GET /api/v1/stations/inactive/.

             Local                             Production
             -----                             ----------
honcho        → station_heartbeat (management  CloudWatch (every 60s)
  heartbeat     command) → station_heartbeat_      → Lambda (this)
                check()                                   → POST /internal/stations/heartbeat/
                                                              → station_heartbeat_check()

Environment variables required:
  DJANGO_INTERNAL_URL   e.g. http://internal-alb.bikeshare.internal/internal/stations/heartbeat/
  INTERNAL_API_SECRET   Shared secret — must match INTERNAL_API_SECRET in Django settings.
"""
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

    The CloudWatch event payload is ignored — this Lambda is purely clock-driven.
    """
    req = urllib.request.Request(
        DJANGO_INTERNAL_URL,
        headers={
            "Content-Type": "application/json",
            "X-Internal-Secret": INTERNAL_API_SECRET,
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            import json
            body = json.loads(resp.read().decode())
            marked_inactive = body.get("marked_inactive", 0)
            if marked_inactive:
                logger.warning(f"Marked {marked_inactive} station(s) INACTIVE")
            else:
                logger.info("Station heartbeat: all stations healthy")
            return {"statusCode": resp.status, "marked_inactive": marked_inactive}
    except urllib.error.HTTPError as e:
        logger.error(f"Django returned {e.code}: {e.read().decode()}")
        raise
    except Exception as e:
        logger.error(f"Station heartbeat failed: {e}")
        raise
