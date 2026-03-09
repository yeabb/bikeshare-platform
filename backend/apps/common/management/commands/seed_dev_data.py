"""
Management command: seed_dev_data

Reads simulator/fleet.yml and populates the database with stations, docks,
bikes, and test users. Safe to run multiple times — uses get_or_create
throughout so it won't duplicate data.

Usage:
    python manage.py seed_dev_data
    python manage.py seed_dev_data --fleet ../simulator/fleet.yml
"""

import yaml
from pathlib import Path

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.bikes.models import Bike, BikeStatus
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
            self._seed_stations(config.get("stations", []))
            self._seed_users(config.get("users", []))

        self.stdout.write(self.style.SUCCESS("Seed complete."))

    def _seed_stations(self, stations_config):
        for station_cfg in stations_config:
            station, created = Station.objects.get_or_create(
                id=station_cfg["id"],
                defaults={
                    "name": station_cfg["name"],
                    "lat": station_cfg["lat"],
                    "lng": station_cfg["lng"],
                    "status": StationStatus.ACTIVE,
                    "total_docks": len(station_cfg["docks"]),
                },
            )
            action = "Created" if created else "Found"
            self.stdout.write(f"  {action} station {station.id} — {station.name}")

            self._seed_docks(station, station_cfg["docks"])

    def _seed_docks(self, station, docks_config):
        for dock_cfg in docks_config:
            dock, created = Dock.objects.get_or_create(
                station=station,
                dock_index=dock_cfg["index"],
                defaults={"state": DockState.AVAILABLE},
            )

            bike_id = dock_cfg.get("bike_id")

            if bike_id:
                # Create or find the bike
                bike, bike_created = Bike.objects.get_or_create(
                    id=bike_id,
                    defaults={
                        "status": BikeStatus.AVAILABLE,
                        "current_station": station,
                        "current_dock": dock,
                    },
                )

                # If bike already existed, make sure its location is correct
                if not bike_created:
                    bike.current_station = station
                    bike.current_dock = dock
                    bike.status = BikeStatus.AVAILABLE
                    bike.save(update_fields=["current_station", "current_dock", "status", "updated_at"])

                # Keep dock in sync with bike
                dock.state = DockState.OCCUPIED
                dock.current_bike = bike
                dock.save(update_fields=["state", "current_bike", "updated_at"])

                b_action = "Created" if bike_created else "Found"
                self.stdout.write(f"    Dock {dock.display_id} — {b_action} bike {bike_id}")
            else:
                dock.state = DockState.AVAILABLE
                dock.current_bike = None
                dock.save(update_fields=["state", "current_bike", "updated_at"])
                self.stdout.write(f"    Dock {dock.display_id} — empty")

    def _seed_users(self, users_config):
        for user_cfg in users_config:
            user, created = User.objects.get_or_create(phone=user_cfg["phone"])
            if created:
                user.status = "ACTIVE"
                user.save(update_fields=["status"])
            action = "Created" if created else "Found"
            self.stdout.write(f"  {action} user {user.phone}")
