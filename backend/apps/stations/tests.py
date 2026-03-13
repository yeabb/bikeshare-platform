from datetime import datetime
from datetime import timezone as dt_timezone

from django.test import TestCase
from django.utils import timezone

from apps.bikes.models import Bike, BikeStatus
from apps.commands.models import Command, CommandStatus
from apps.rides.models import Ride, RideStatus
from apps.stations.models import Dock, DockState, Station, StationStatus
from apps.stations.services import reconcile_telemetry, station_heartbeat_check
from apps.users.models import User


# --- Helpers ---

def make_station(station_id="S001"):
    return Station.objects.create(
        id=station_id, name="Test Station", lat=0, lng=0, total_docks=2
    )


def make_dock(station, dock_index=1, state=DockState.AVAILABLE, bike=None, fault_code=""):
    dock = Dock.objects.create(
        station=station,
        dock_index=dock_index,
        state=state,
        current_bike=bike,
        fault_code=fault_code,
    )
    return dock


def make_bike(bike_id="B001", station=None, dock=None, status=BikeStatus.AVAILABLE):
    bike = Bike.objects.create(
        id=bike_id, status=status, current_station=station, current_dock=dock
    )
    if dock:
        dock.current_bike = bike
        dock.save(update_fields=["current_bike"])
    return bike


def snap(dock_id, state, bike_id=None, fault_code=None):
    """Build a single dock entry as it would appear in a STATION_TELEMETRY payload."""
    return {"dockId": dock_id, "state": state, "bikeId": bike_id, "faultCode": fault_code}


# --- Tests ---

class ReconcileTelemetryNoOpTests(TestCase):
    """Telemetry that matches DB state should produce no writes."""

    def setUp(self):
        self.station = make_station()

    def test_available_matches_available(self):
        dock = make_dock(self.station, state=DockState.AVAILABLE)
        reconcile_telemetry("S001", [snap(1, "AVAILABLE")])
        dock.refresh_from_db()
        self.assertEqual(dock.state, DockState.AVAILABLE)

    def test_occupied_matches_occupied_same_bike(self):
        bike = make_bike()
        dock = make_dock(self.station, state=DockState.OCCUPIED, bike=bike)
        reconcile_telemetry("S001", [snap(1, "OCCUPIED", "B001")])
        dock.refresh_from_db()
        self.assertEqual(dock.state, DockState.OCCUPIED)
        self.assertEqual(dock.current_bike_id, "B001")

    def test_fault_matches_fault_same_code(self):
        dock = make_dock(self.station, state=DockState.FAULT, fault_code="SENSOR_ERROR")
        reconcile_telemetry("S001", [snap(1, "FAULT", fault_code="SENSOR_ERROR")])
        dock.refresh_from_db()
        self.assertEqual(dock.state, DockState.FAULT)
        self.assertEqual(dock.fault_code, "SENSOR_ERROR")

    def test_unlocking_dock_is_skipped(self):
        """UNLOCKING docks are owned by the command TTL sweep — telemetry must not touch them."""
        dock = make_dock(self.station, state=DockState.UNLOCKING)
        reconcile_telemetry("S001", [snap(1, "AVAILABLE")])
        dock.refresh_from_db()
        self.assertEqual(dock.state, DockState.UNLOCKING)

    def test_unknown_dock_does_not_raise(self):
        """Telemetry for a dock not in the DB should be silently skipped."""
        reconcile_telemetry("S001", [snap(99, "AVAILABLE")])  # dock_index 99 doesn't exist

    def test_bike_mismatch_does_not_autocorrect(self):
        """DB and telemetry disagree on which bike is docked — log only, no write."""
        bike = make_bike("B001")
        dock = make_dock(self.station, state=DockState.OCCUPIED, bike=bike)
        reconcile_telemetry("S001", [snap(1, "OCCUPIED", "B002")])
        dock.refresh_from_db()
        self.assertEqual(dock.current_bike_id, "B001")  # unchanged


class ReconcileTelemetryCorrectionTests(TestCase):
    """Telemetry that disagrees with DB state should correct the DB."""

    def setUp(self):
        self.station = make_station()

    def test_corrects_missed_bike_undocked(self):
        """DB=OCCUPIED, telemetry=AVAILABLE → dock cleared (missed BIKE_UNDOCKED)."""
        bike = make_bike()
        dock = make_dock(self.station, state=DockState.OCCUPIED, bike=bike)

        reconcile_telemetry("S001", [snap(1, "AVAILABLE")])

        dock.refresh_from_db()
        self.assertEqual(dock.state, DockState.AVAILABLE)
        self.assertIsNone(dock.current_bike_id)

    def test_corrects_missed_bike_docked(self):
        """DB=AVAILABLE, telemetry=OCCUPIED → dock set (missed BIKE_DOCKED)."""
        bike = make_bike("B001")
        dock = make_dock(self.station, state=DockState.AVAILABLE)

        reconcile_telemetry("S001", [snap(1, "OCCUPIED", "B001")])

        dock.refresh_from_db()
        self.assertEqual(dock.state, DockState.OCCUPIED)
        self.assertEqual(dock.current_bike_id, "B001")

    def test_corrects_missed_bike_docked_syncs_bike_location(self):
        """When correcting AVAILABLE→OCCUPIED, bike.current_dock should be updated."""
        bike = make_bike("B001")
        dock = make_dock(self.station, state=DockState.AVAILABLE)

        reconcile_telemetry("S001", [snap(1, "OCCUPIED", "B001")])

        bike.refresh_from_db()
        self.assertEqual(bike.current_dock_id, dock.id)
        self.assertEqual(bike.current_station_id, "S001")

    def test_missed_bike_docked_does_not_end_active_ride(self):
        """Correcting AVAILABLE→OCCUPIED must never touch an active ride."""
        user = User.objects.create_user(phone="+15550000001")
        bike = make_bike("B001", status=BikeStatus.IN_USE)
        dock = make_dock(self.station, state=DockState.AVAILABLE)
        command = Command.objects.create(
            user=user, station=self.station, dock=dock, bike=bike,
            status=CommandStatus.SUCCESS,
            expires_at=timezone.now() + timezone.timedelta(seconds=10),
        )
        ride = Ride.objects.create(
            user=user, bike=bike, unlock_command=command,
            start_station=self.station, start_dock=dock,
            started_at=timezone.now(), status=RideStatus.ACTIVE,
        )

        reconcile_telemetry("S001", [snap(1, "OCCUPIED", "B001")])

        ride.refresh_from_db()
        self.assertEqual(ride.status, RideStatus.ACTIVE)

    def test_corrects_missed_dock_fault(self):
        """DB=OCCUPIED, telemetry=FAULT → dock set to FAULT (missed DOCK_FAULT)."""
        bike = make_bike()
        dock = make_dock(self.station, state=DockState.OCCUPIED, bike=bike)

        reconcile_telemetry("S001", [snap(1, "FAULT", fault_code="LATCH_STUCK")])

        dock.refresh_from_db()
        self.assertEqual(dock.state, DockState.FAULT)
        self.assertEqual(dock.fault_code, "LATCH_STUCK")

    def test_corrects_fault_cleared_to_occupied(self):
        """DB=FAULT, telemetry=OCCUPIED → fault cleared, dock occupied."""
        bike = make_bike("B001")
        dock = make_dock(self.station, state=DockState.FAULT, fault_code="SENSOR_ERROR")

        reconcile_telemetry("S001", [snap(1, "OCCUPIED", "B001")])

        dock.refresh_from_db()
        self.assertEqual(dock.state, DockState.OCCUPIED)
        self.assertEqual(dock.fault_code, "")
        self.assertEqual(dock.current_bike_id, "B001")

    def test_corrects_fault_cleared_to_available(self):
        """DB=FAULT, telemetry=AVAILABLE → fault cleared, dock empty."""
        dock = make_dock(self.station, state=DockState.FAULT, fault_code="POWER_FAULT")

        reconcile_telemetry("S001", [snap(1, "AVAILABLE")])

        dock.refresh_from_db()
        self.assertEqual(dock.state, DockState.AVAILABLE)
        self.assertEqual(dock.fault_code, "")
        self.assertIsNone(dock.current_bike_id)

    def test_updates_fault_code_when_changed(self):
        """DB=FAULT(CODE_A), telemetry=FAULT(CODE_B) → fault code updated."""
        dock = make_dock(self.station, state=DockState.FAULT, fault_code="SENSOR_ERROR")

        reconcile_telemetry("S001", [snap(1, "FAULT", fault_code="POWER_FAULT")])

        dock.refresh_from_db()
        self.assertEqual(dock.state, DockState.FAULT)
        self.assertEqual(dock.fault_code, "POWER_FAULT")

    def test_multiple_docks_corrected_in_one_call(self):
        """All docks in a snapshot are processed in a single transaction."""
        bike = make_bike("B001")
        dock1 = make_dock(self.station, dock_index=1, state=DockState.OCCUPIED, bike=bike)
        dock2 = make_dock(self.station, dock_index=2, state=DockState.AVAILABLE)

        reconcile_telemetry("S001", [
            snap(1, "AVAILABLE"),       # missed BIKE_UNDOCKED
            snap(2, "FAULT", fault_code="SENSOR_ERROR"),  # missed DOCK_FAULT
        ])

        dock1.refresh_from_db()
        dock2.refresh_from_db()
        self.assertEqual(dock1.state, DockState.AVAILABLE)
        self.assertIsNone(dock1.current_bike_id)
        self.assertEqual(dock2.state, DockState.FAULT)
        self.assertEqual(dock2.fault_code, "SENSOR_ERROR")


class ReconcileTelemetryHeartbeatTests(TestCase):
    """reconcile_telemetry() should update last_telemetry_at and restore INACTIVE stations."""

    def test_updates_last_telemetry_at(self):
        station = make_station()
        self.assertIsNone(station.last_telemetry_at)

        reconcile_telemetry("S001", [])

        station.refresh_from_db()
        self.assertIsNotNone(station.last_telemetry_at)

    def test_restores_inactive_station_to_active(self):
        station = make_station()
        station.status = StationStatus.INACTIVE
        station.save()

        reconcile_telemetry("S001", [])

        station.refresh_from_db()
        self.assertEqual(station.status, StationStatus.ACTIVE)

    def test_unknown_station_does_not_raise(self):
        reconcile_telemetry("UNKNOWN", [])  # should silently return


class StationHeartbeatCheckTests(TestCase):
    """station_heartbeat_check() flags silent stations as INACTIVE."""

    def test_flags_stale_station(self):
        """Station with last_telemetry_at older than 90s is marked INACTIVE."""
        station = make_station()
        station.last_telemetry_at = timezone.now() - timezone.timedelta(seconds=120)
        station.save()

        count = station_heartbeat_check()

        self.assertEqual(count, 1)
        station.refresh_from_db()
        self.assertEqual(station.status, StationStatus.INACTIVE)

    def test_does_not_flag_recent_station(self):
        """Station that reported recently is left ACTIVE."""
        station = make_station()
        station.last_telemetry_at = timezone.now() - timezone.timedelta(seconds=30)
        station.save()

        count = station_heartbeat_check()

        self.assertEqual(count, 0)
        station.refresh_from_db()
        self.assertEqual(station.status, StationStatus.ACTIVE)

    def test_flags_never_reported_past_grace_period(self):
        """Station that never reported and was created more than 5 min ago is flagged."""
        station = make_station()
        # Backdate created_at past the grace period
        Station.objects.filter(id="S001").update(
            created_at=timezone.now() - timezone.timedelta(minutes=10)
        )

        count = station_heartbeat_check()

        self.assertEqual(count, 1)
        station.refresh_from_db()
        self.assertEqual(station.status, StationStatus.INACTIVE)

    def test_does_not_flag_never_reported_within_grace_period(self):
        """Brand new station that hasn't reported yet is given a grace period."""
        make_station()  # just created — created_at is now

        count = station_heartbeat_check()

        self.assertEqual(count, 0)

    def test_does_not_flag_already_inactive_station(self):
        """Already INACTIVE stations are not re-processed."""
        station = make_station()
        station.status = StationStatus.INACTIVE
        station.last_telemetry_at = timezone.now() - timezone.timedelta(seconds=120)
        station.save()

        count = station_heartbeat_check()

        self.assertEqual(count, 0)

    def test_flags_multiple_stale_stations(self):
        """All stale stations in one pass."""
        for sid in ["S001", "S002", "S003"]:
            s = Station.objects.create(id=sid, name=sid, lat=0, lng=0, total_docks=1)
            s.last_telemetry_at = timezone.now() - timezone.timedelta(seconds=120)
            s.save()

        count = station_heartbeat_check()

        self.assertEqual(count, 3)


class InactiveStationsEndpointTests(TestCase):
    """GET /api/v1/stations/inactive returns currently downed stations."""

    def setUp(self):
        self.user = User.objects.create_user(phone="+15550000001")
        from rest_framework_simplejwt.tokens import AccessToken
        self.token = str(AccessToken.for_user(self.user))

    def _get(self):
        return self.client.get(
            "/api/v1/stations/inactive",
            HTTP_AUTHORIZATION=f"Bearer {self.token}",
        )

    def test_returns_empty_when_all_active(self):
        make_station()
        resp = self._get()
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["count"], 0)

    def test_returns_inactive_stations(self):
        station = make_station()
        station.status = StationStatus.INACTIVE
        station.save()

        resp = self._get()
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["count"], 1)
        self.assertEqual(resp.json()["stations"][0]["station_id"], "S001")

    def test_requires_authentication(self):
        resp = self.client.get("/api/v1/stations/inactive")
        self.assertEqual(resp.status_code, 401)


def make_active_ride(bike, station, dock, user):
    """Create a Command + ACTIVE Ride for the given bike. Returns the Ride."""
    from apps.rides.services import start_ride

    command = Command.objects.create(
        user=user,
        station=station,
        dock=dock,
        bike=bike,
        status=CommandStatus.SUCCESS,
        expires_at=timezone.now() + timezone.timedelta(seconds=10),
        resolved_at=timezone.now(),
    )
    return start_ride(command)


class StaleRideReconciliationTests(TestCase):
    """
    Two-snapshot stale ride reconciliation.

    When a BIKE_DOCKED event is missed, periodic telemetry is used to
    detect and end stale rides. Two consecutive OCCUPIED snapshots are
    required before ending the ride to avoid false positives.
    """

    def setUp(self):
        self.user = User.objects.create_user(phone="+15550000099")
        self.station = make_station()
        # Dock starts AVAILABLE — bike has undocked but BIKE_DOCKED was missed
        self.dock = make_dock(self.station, state=DockState.AVAILABLE)
        self.bike = make_bike(bike_id="B001", station=self.station)
        self.ride = make_active_ride(self.bike, self.station, self.dock, self.user)
        # first_ts simulates when the bike actually returned (60s ago)
        self.first_ts = int((timezone.now() - timezone.timedelta(seconds=60)).timestamp())
        self.second_ts = int(timezone.now().timestamp())

    def test_first_snapshot_sets_suspected_return_at(self):
        """AVAILABLE→OCCUPIED with active ride sets suspected_return_at, ride stays ACTIVE."""
        reconcile_telemetry("S001", [snap(1, "OCCUPIED", "B001")], telemetry_ts=self.first_ts)

        self.ride.refresh_from_db()
        self.assertEqual(self.ride.status, RideStatus.ACTIVE)
        self.assertIsNotNone(self.ride.suspected_return_at)

    def test_first_snapshot_suspected_return_at_matches_telemetry_ts(self):
        """suspected_return_at is set to the telemetry timestamp, not now()."""
        expected = datetime.fromtimestamp(self.first_ts, tz=dt_timezone.utc)

        reconcile_telemetry("S001", [snap(1, "OCCUPIED", "B001")], telemetry_ts=self.first_ts)

        self.ride.refresh_from_db()
        self.assertEqual(self.ride.suspected_return_at, expected)

    def test_second_snapshot_ends_stale_ride(self):
        """Two consecutive OCCUPIED snapshots complete the ride."""
        reconcile_telemetry("S001", [snap(1, "OCCUPIED", "B001")], telemetry_ts=self.first_ts)
        reconcile_telemetry("S001", [snap(1, "OCCUPIED", "B001")], telemetry_ts=self.second_ts)

        self.ride.refresh_from_db()
        self.assertEqual(self.ride.status, RideStatus.COMPLETED)

    def test_stale_ride_ended_at_uses_first_snapshot_time(self):
        """ended_at is the first snapshot timestamp, not second — billing reflects actual return time."""
        expected_ended_at = datetime.fromtimestamp(self.first_ts, tz=dt_timezone.utc)

        reconcile_telemetry("S001", [snap(1, "OCCUPIED", "B001")], telemetry_ts=self.first_ts)
        reconcile_telemetry("S001", [snap(1, "OCCUPIED", "B001")], telemetry_ts=self.second_ts)

        self.ride.refresh_from_db()
        self.assertEqual(self.ride.ended_at, expected_ended_at)

    def test_second_snapshot_clears_suspected_return_at(self):
        """suspected_return_at is cleared when the ride is ended."""
        reconcile_telemetry("S001", [snap(1, "OCCUPIED", "B001")], telemetry_ts=self.first_ts)
        reconcile_telemetry("S001", [snap(1, "OCCUPIED", "B001")], telemetry_ts=self.second_ts)

        self.ride.refresh_from_db()
        self.assertIsNone(self.ride.suspected_return_at)

    def test_bike_leaves_before_second_snapshot_clears_suspected_return_at(self):
        """Bike departing before second snapshot clears suspected_return_at — ride stays ACTIVE."""
        reconcile_telemetry("S001", [snap(1, "OCCUPIED", "B001")], telemetry_ts=self.first_ts)
        self.ride.refresh_from_db()
        self.assertIsNotNone(self.ride.suspected_return_at)

        # Dock is now OCCUPIED in DB. Next snapshot shows AVAILABLE — bike left again.
        reconcile_telemetry("S001", [snap(1, "AVAILABLE")], telemetry_ts=self.second_ts)

        self.ride.refresh_from_db()
        self.assertEqual(self.ride.status, RideStatus.ACTIVE)
        self.assertIsNone(self.ride.suspected_return_at)

    def test_no_active_ride_does_not_set_suspected_return_at(self):
        """If the bike has no active ride, suspected_return_at is never set."""
        self.ride.status = RideStatus.COMPLETED
        self.ride.save()

        reconcile_telemetry("S001", [snap(1, "OCCUPIED", "B001")], telemetry_ts=self.first_ts)

        self.ride.refresh_from_db()
        self.assertIsNone(self.ride.suspected_return_at)


INTERNAL_SECRET = "test-heartbeat-secret"
HEARTBEAT_ENDPOINT = "/internal/stations/heartbeat/"


class InternalHeartbeatAuthTests(TestCase):
    """Endpoint rejects requests without a valid secret."""

    def test_missing_secret_returns_401(self):
        resp = self.client.post(HEARTBEAT_ENDPOINT)
        self.assertEqual(resp.status_code, 401)

    def test_wrong_secret_returns_401(self):
        resp = self.client.post(
            HEARTBEAT_ENDPOINT,
            headers={"X-Internal-Secret": "wrong"},
        )
        self.assertEqual(resp.status_code, 401)

    def test_get_method_not_allowed(self):
        resp = self.client.get(HEARTBEAT_ENDPOINT)
        self.assertEqual(resp.status_code, 405)


class InternalHeartbeatTests(TestCase):
    """Endpoint runs the heartbeat check and returns the count."""

    def _post(self):
        from django.test import override_settings
        with override_settings(INTERNAL_API_SECRET=INTERNAL_SECRET):
            return self.client.post(
                HEARTBEAT_ENDPOINT,
                headers={"X-Internal-Secret": INTERNAL_SECRET},
            )

    def test_returns_zero_when_all_stations_healthy(self):
        make_station()
        resp = self._post()
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"marked_inactive": 0})

    def test_marks_silent_station_inactive(self):
        station = make_station()
        # Station has not sent telemetry — last_telemetry_at is old enough to trip the threshold
        station.last_telemetry_at = timezone.now() - timezone.timedelta(seconds=200)
        station.save()

        resp = self._post()
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["marked_inactive"], 1)

        station.refresh_from_db()
        self.assertEqual(station.status, StationStatus.INACTIVE)
