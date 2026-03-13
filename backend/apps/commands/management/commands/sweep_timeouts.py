"""
Management command: sweep_timeouts

Runs continuously, checking every SWEEP_INTERVAL_SEC seconds for PENDING
commands that have passed their expires_at and marking them TIMEOUT.

Local dev:  runs as a process managed by honcho (see Procfile)
Production: replaced by infra/aws/lambdas/timeout_sweep/ triggered by a CloudWatch
            Scheduled Rule (rate(10 seconds)) — same sweep_timed_out_commands() function,
            different trigger.

Usage:
    python manage.py sweep_timeouts
    python manage.py sweep_timeouts --interval 10
"""
import time
import logging

from django.core.management.base import BaseCommand

from apps.commands.services import sweep_timed_out_commands

logger = logging.getLogger(__name__)

SWEEP_INTERVAL_SEC = 5


class Command(BaseCommand):
    help = "Continuously sweeps PENDING commands past expires_at → TIMEOUT"

    def add_arguments(self, parser):
        parser.add_argument(
            "--interval",
            type=int,
            default=SWEEP_INTERVAL_SEC,
            help=f"Seconds between sweeps (default: {SWEEP_INTERVAL_SEC})",
        )

    def handle(self, *args, **options):
        interval = options["interval"]
        self.stdout.write(f"Timeout sweep started — running every {interval}s")

        while True:
            try:
                swept = sweep_timed_out_commands()
                if swept:
                    logger.warning(f"Swept {swept} timed-out command(s) → TIMEOUT")
            except Exception:
                logger.exception("Error during timeout sweep — will retry next interval")

            time.sleep(interval)
