from django.test import TestCase
from django.utils import timezone

from apps.bikes.models import Bike, BikeStatus
from apps.commands.models import Command, CommandStatus
from apps.commands.services import create_unlock_command, handle_unlock_result
from apps.rides.models import Ride, RideStatus
from apps.stations.models import Dock, DockState, Station
from apps.users.models import User


def make_user(phone="+15550000001"):
    return User.objects.create_user(phone=phone)


def make_station(station_id="S001"):
    return Station.objects.create(
        id=station_id, name="Test Station", lat=0, lng=0, total_docks=2
    )


def make_dock(station, dock_index=1, state=DockState.OCCUPIED):
    return Dock.objects.create(station=station, dock_index=dock_index, state=state)


def make_bike(bike_id="B001", station=None, dock=None, status=BikeStatus.AVAILABLE):
    bike = Bike.objects.create(id=bike_id, status=status, current_station=station, current_dock=dock)
    if dock:
        dock.current_bike = bike
        dock.save(update_fields=["current_bike"])
    return bike


class CreateUnlockCommandTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.station = make_station()
        self.dock = make_dock(self.station)
        self.bike = make_bike("B001", self.station, self.dock)

    def test_creates_pending_command(self):
        command, error = create_unlock_command(self.user, "B001")

        self.assertIsNone(error)
        self.assertIsNotNone(command)
        self.assertEqual(command.status, CommandStatus.PENDING)
        self.assertEqual(command.bike_id, "B001")
        self.assertEqual(command.station_id, "S001")

    def test_dock_transitions_to_unlocking(self):
        create_unlock_command(self.user, "B001")
        self.dock.refresh_from_db()
        self.assertEqual(self.dock.state, DockState.UNLOCKING)

    def test_rejects_unknown_bike(self):
        _, error = create_unlock_command(self.user, "UNKNOWN")
        self.assertEqual(error, "BIKE_NOT_FOUND")

    def test_rejects_bike_in_use(self):
        self.bike.status = BikeStatus.IN_USE
        self.bike.save()
        _, error = create_unlock_command(self.user, "B001")
        self.assertEqual(error, "BIKE_NOT_AVAILABLE")

    def test_rejects_undocked_bike(self):
        self.bike.current_dock = None
        self.bike.save()
        _, error = create_unlock_command(self.user, "B001")
        self.assertEqual(error, "BIKE_NOT_DOCKED")

    def test_rejects_if_active_ride_exists(self):
        # Create an active ride manually
        command = Command.objects.create(
            user=self.user, station=self.station, dock=self.dock, bike=self.bike,
            status=CommandStatus.SUCCESS,
            expires_at=timezone.now() + timezone.timedelta(seconds=10),
        )
        Ride.objects.create(
            user=self.user, bike=self.bike, unlock_command=command,
            start_station=self.station, start_dock=self.dock,
            started_at=timezone.now(), status=RideStatus.ACTIVE,
        )
        _, error = create_unlock_command(self.user, "B001")
        self.assertEqual(error, "ACTIVE_RIDE_EXISTS")

    def test_rejects_if_pending_command_exists(self):
        Command.objects.create(
            user=self.user, station=self.station, dock=self.dock, bike=self.bike,
            status=CommandStatus.PENDING,
            expires_at=timezone.now() + timezone.timedelta(seconds=10),
        )
        _, error = create_unlock_command(self.user, "B001")
        self.assertEqual(error, "PENDING_COMMAND_EXISTS")


class HandleUnlockResultTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.station = make_station()
        self.dock = make_dock(self.station, state=DockState.UNLOCKING)
        self.bike = make_bike("B001", self.station, self.dock, status=BikeStatus.AVAILABLE)
        self.command = Command.objects.create(
            user=self.user, station=self.station, dock=self.dock, bike=self.bike,
            status=CommandStatus.PENDING,
            expires_at=timezone.now() + timezone.timedelta(seconds=10),
        )

    def test_success_creates_ride(self):
        handle_unlock_result(str(self.command.request_id), "SUCCESS")

        self.command.refresh_from_db()
        self.assertEqual(self.command.status, CommandStatus.SUCCESS)
        self.assertIsNotNone(self.command.resolved_at)

        ride = Ride.objects.get(unlock_command=self.command)
        self.assertEqual(ride.status, RideStatus.ACTIVE)
        self.assertEqual(ride.user, self.user)
        self.assertEqual(ride.bike, self.bike)

        self.bike.refresh_from_db()
        self.assertEqual(self.bike.status, BikeStatus.IN_USE)

    def test_failure_does_not_create_ride(self):
        handle_unlock_result(str(self.command.request_id), "FAILED", "LATCH_FAULT")

        self.command.refresh_from_db()
        self.assertEqual(self.command.status, CommandStatus.FAILED)
        self.assertEqual(self.command.failure_reason, "LATCH_FAULT")

        self.assertFalse(Ride.objects.filter(unlock_command=self.command).exists())

        self.dock.refresh_from_db()
        self.assertEqual(self.dock.state, DockState.OCCUPIED)

    def test_idempotent_on_success(self):
        handle_unlock_result(str(self.command.request_id), "SUCCESS")
        # Calling again should not create a second ride or raise an error
        handle_unlock_result(str(self.command.request_id), "SUCCESS")
        self.assertEqual(Ride.objects.filter(unlock_command=self.command).count(), 1)

    def test_idempotent_on_failure(self):
        handle_unlock_result(str(self.command.request_id), "FAILED", "LATCH_FAULT")
        handle_unlock_result(str(self.command.request_id), "FAILED", "LATCH_FAULT")
        self.command.refresh_from_db()
        self.assertEqual(self.command.status, CommandStatus.FAILED)

    def test_unknown_request_id_is_ignored(self):
        # Should not raise
        handle_unlock_result("00000000-0000-0000-0000-000000000000", "SUCCESS")


VALID_SECRET = "test-secret-abc123"
SWEEP_ENDPOINT = "/internal/commands/sweep/"


class InternalSweepAuthTests(TestCase):
    """Endpoint rejects requests without a valid secret."""

    def test_missing_secret_returns_401(self):
        resp = self.client.post(SWEEP_ENDPOINT)
        self.assertEqual(resp.status_code, 401)

    def test_wrong_secret_returns_401(self):
        resp = self.client.post(
            SWEEP_ENDPOINT,
            headers={"X-Internal-Secret": "wrong"},
        )
        self.assertEqual(resp.status_code, 401)

    def test_get_method_not_allowed(self):
        resp = self.client.get(SWEEP_ENDPOINT)
        self.assertEqual(resp.status_code, 405)


class InternalSweepTests(TestCase):
    """Endpoint runs the sweep and returns the count."""

    def _post(self):
        from django.test import override_settings
        with override_settings(INTERNAL_API_SECRET=VALID_SECRET):
            return self.client.post(
                SWEEP_ENDPOINT,
                headers={"X-Internal-Secret": VALID_SECRET},
            )

    def test_returns_zero_when_nothing_to_sweep(self):
        resp = self._post()
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"swept": 0})

    def test_sweeps_expired_pending_command(self):
        user = make_user()
        station = make_station()
        dock = make_dock(station)
        bike = make_bike(station=station, dock=dock)

        # Create a PENDING command already past expires_at
        Command.objects.create(
            user=user,
            station=station,
            dock=dock,
            bike=bike,
            status=CommandStatus.PENDING,
            expires_at=timezone.now() - timezone.timedelta(seconds=1),
        )

        resp = self._post()
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"swept": 1})
