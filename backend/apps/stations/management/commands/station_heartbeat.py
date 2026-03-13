"""
Management command: station_heartbeat

Runs continuously, checking every HEARTBEAT_INTERVAL_SEC seconds for ACTIVE
stations that have stopped sending telemetry and marking them INACTIVE.

Local dev:  runs as the `heartbeat` process managed by honcho (see Procfile)
Production: replaced by infra/aws/lambdas/station_heartbeat/ triggered by a CloudWatch
            Scheduled Rule (rate(1 minute)) — same station_heartbeat_check() function,
            different trigger.

Usage:
    python manage.py station_heartbeat
    python manage.py station_heartbeat --interval 60
"""
import time
import logging

from django.core.management.base import BaseCommand

from apps.stations.services import station_heartbeat_check

logger = logging.getLogger(__name__)

HEARTBEAT_INTERVAL_SEC = 60


class Command(BaseCommand):
    help = "Continuously checks for silent stations and marks them INACTIVE"

    def add_arguments(self, parser):
        parser.add_argument(
            "--interval",
            type=int,
            default=HEARTBEAT_INTERVAL_SEC,
            help=f"Seconds between checks (default: {HEARTBEAT_INTERVAL_SEC})",
        )

    def handle(self, *args, **options):
        interval = options["interval"]
        self.stdout.write(f"Station heartbeat started — running every {interval}s")

        while True:
            try:
                count = station_heartbeat_check()
                if count:
                    logger.warning(f"Marked {count} station(s) INACTIVE")
            except Exception:
                logger.exception("Error during heartbeat check — will retry next interval")

            time.sleep(interval)
