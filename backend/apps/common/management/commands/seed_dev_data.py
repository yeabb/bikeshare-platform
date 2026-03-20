"""
Management command: seed_dev_data

Wipes all existing data and repopulates the database from simulator/fleet.yml.
Running this multiple times always produces a clean state matching the fleet config.

Usage:
    python manage.py seed_dev_data
    python manage.py seed_dev_data --fleet ../simulator/fleet.yml
"""

import yaml
from pathlib import Path

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.bikes.models import Bike, BikeStatus
from apps.rides.models import Ride
from apps.commands.models import Command as UnlockCommand
from apps.stations.models import Dock, DockState, Station, StationStatus
from apps.users.models import User


FLEET_YML_DEFAULT = Path(__file__).resolve().parents[5] / "simulator" / "fleet.yml"


class Command(BaseCommand):
    help = "Seed the database with dev data from simulator/fleet.yml"

    def add_arguments(self, parser):
        parser.add_argument(
            "--fleet",
            type=str,
            default=str(FLEET_YML_DEFAULT),
            help="Path to fleet.yml config file",
        )

    def handle(self, *args, **options):
        fleet_path = Path(options["fleet"])

        if not fleet_path.exists():
            self.stderr.write(f"Fleet config not found: {fleet_path}")
            return

        with open(fleet_path) as f:
            config = yaml.safe_load(f)

        self.stdout.write(f"Loading fleet config from {fleet_path}")

        with transaction.atomic():
            self._wipe()
            self._seed_stations(config.get("stations", []))
            self._seed_users(config.get("users", []))

        self.stdout.write(self.style.SUCCESS("Seed complete."))

    def _wipe(self):
        Ride.objects.all().delete()
        UnlockCommand.objects.all().delete()
        Bike.objects.all().delete()
        Dock.objects.all().delete()
        Station.objects.all().delete()
        User.objects.all().delete()
        self.stdout.write("  Wiped existing data.")

    def _seed_stations(self, stations_config):
        for station_cfg in stations_config:
            station = Station.objects.create(
                id=station_cfg["id"],
                name=station_cfg["name"],
                lat=station_cfg["lat"],
                lng=station_cfg["lng"],
                status=StationStatus.ACTIVE,
                total_docks=len(station_cfg["docks"]),
            )
            self.stdout.write(f"  Created station {station.id} — {station.name}")
            self._seed_docks(station, station_cfg["docks"])

    def _seed_docks(self, station, docks_config):
        for dock_cfg in docks_config:
            dock = Dock.objects.create(
                station=station,
                dock_index=dock_cfg["index"],
                state=DockState.AVAILABLE,
            )

            bike_id = dock_cfg.get("bike_id")
            if bike_id:
                bike = Bike.objects.create(
                    id=bike_id,
                    status=BikeStatus.AVAILABLE,
                    current_station=station,
                    current_dock=dock,
                )
                dock.state = DockState.OCCUPIED
                dock.current_bike = bike
                dock.save(update_fields=["state", "current_bike", "updated_at"])
                self.stdout.write(f"    Dock {dock.display_id} — bike {bike_id}")
            else:
                self.stdout.write(f"    Dock {dock.display_id} — empty")

    def _seed_users(self, users_config):
        for user_cfg in users_config:
            User.objects.create(phone=user_cfg["phone"], status="ACTIVE")
            self.stdout.write(f"  Created user {user_cfg['phone']}")
