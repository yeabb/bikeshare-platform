"""
Lambda: Timeout Sweep

Triggered by a CloudWatch Scheduled Rule every 10 seconds.

Calls the Django internal sweep endpoint, which finds all PENDING commands
that have passed their expires_at and marks them TIMEOUT. The dock is
restored to OCCUPIED so another user can unlock it.

             Local                             Production
             -----                             ----------
honcho sweep → sweep_timeouts (management     CloudWatch (every 10s)
               command) → sweep_timed_out_        → Lambda (this)
               commands()                             → POST /internal/commands/sweep/
                                                          → sweep_timed_out_commands()

Environment variables required:
  DJANGO_INTERNAL_URL   e.g. http://internal-alb.bikeshare.internal/internal/commands/sweep/
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
            swept = body.get("swept", 0)
            if swept:
                logger.warning(f"Swept {swept} timed-out command(s) → TIMEOUT")
            else:
                logger.info("Timeout sweep: nothing to sweep")
            return {"statusCode": resp.status, "swept": swept}
    except urllib.error.HTTPError as e:
        logger.error(f"Django returned {e.code}: {e.read().decode()}")
        raise
    except Exception as e:
        logger.error(f"Timeout sweep failed: {e}")
        raise
