from django.test import TestCase
from django.utils import timezone

from apps.bikes.models import Bike, BikeStatus
from apps.commands.models import Command, CommandStatus
from apps.rides.models import Ride, RideStatus
from apps.rides.services import end_ride_on_dock, start_ride
from apps.stations.models import Dock, DockState, Station
from apps.users.models import User


def _setup():
    user = User.objects.create_user(phone="+15550000099")
    station = Station.objects.create(id="S001", name="Start", lat=0, lng=0, total_docks=2)
    end_station = Station.objects.create(id="S002", name="End", lat=1, lng=1, total_docks=2)
    dock = Dock.objects.create(station=station, dock_index=1, state=DockState.UNLOCKING)
    end_dock = Dock.objects.create(station=end_station, dock_index=2, state=DockState.AVAILABLE)
    bike = Bike.objects.create(id="B001", status=BikeStatus.AVAILABLE, current_station=station, current_dock=dock)
    dock.current_bike = bike
    dock.save()
    command = Command.objects.create(
        user=user, station=station, dock=dock, bike=bike,
        status=CommandStatus.SUCCESS,
        expires_at=timezone.now() + timezone.timedelta(seconds=10),
        resolved_at=timezone.now(),
    )
    return user, station, end_station, dock, end_dock, bike, command


class StartRideTests(TestCase):
    def test_creates_active_ride(self):
        user, station, _, dock, _, bike, command = _setup()
        ride = start_ride(command)

        self.assertEqual(ride.status, RideStatus.ACTIVE)
        self.assertEqual(ride.user, user)
        self.assertEqual(ride.bike, bike)
        self.assertEqual(ride.start_station, station)
        self.assertEqual(ride.start_dock, dock)
        self.assertIsNotNone(ride.started_at)

        bike.refresh_from_db()
        self.assertEqual(bike.status, BikeStatus.IN_USE)
        self.assertEqual(bike.current_ride, ride)


class EndRideOnDockTests(TestCase):
    def setUp(self):
        (
            self.user, self.station, self.end_station,
            self.dock, self.end_dock, self.bike, self.command
        ) = _setup()
        self.ride = start_ride(self.command)

    def test_ends_ride_on_dock(self):
        end_ride_on_dock("B001", "S002", 2, event_ts=1234567890)

        self.ride.refresh_from_db()
        self.assertEqual(self.ride.status, RideStatus.COMPLETED)
        self.assertIsNotNone(self.ride.ended_at)
        self.assertEqual(self.ride.end_station, self.end_station)
        self.assertEqual(self.ride.end_dock, self.end_dock)

    def test_bike_becomes_available_after_docking(self):
        end_ride_on_dock("B001", "S002", 2, event_ts=1234567890)

        self.bike.refresh_from_db()
        self.assertEqual(self.bike.status, BikeStatus.AVAILABLE)
        self.assertIsNone(self.bike.current_ride)
        self.assertEqual(self.bike.current_station, self.end_station)
        self.assertEqual(self.bike.current_dock, self.end_dock)

    def test_dock_becomes_occupied_after_docking(self):
        end_ride_on_dock("B001", "S002", 2, event_ts=1234567890)

        self.end_dock.refresh_from_db()
        self.assertEqual(self.end_dock.state, DockState.OCCUPIED)
        self.assertEqual(self.end_dock.current_bike, self.bike)

    def test_idempotent_when_no_active_ride(self):
        end_ride_on_dock("B001", "S002", 2, event_ts=1234567890)
        # Second call should be a no-op
        end_ride_on_dock("B001", "S002", 2, event_ts=1234567890)
        self.ride.refresh_from_db()
        self.assertEqual(self.ride.status, RideStatus.COMPLETED)

    def test_unknown_bike_is_ignored(self):
        # Should not raise
        end_ride_on_dock("UNKNOWN_BIKE", "S002", 2, event_ts=1234567890)

    def test_handles_unknown_end_dock_gracefully(self):
        # Unknown dock — ride still ends, just without end location
        end_ride_on_dock("B001", "S999", 99, event_ts=1234567890)
        self.ride.refresh_from_db()
        self.assertEqual(self.ride.status, RideStatus.COMPLETED)
        self.assertIsNone(self.ride.end_dock)
        self.assertIsNone(self.ride.end_station)
