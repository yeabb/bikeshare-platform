from django.test import TestCase
from django.utils import timezone

from apps.bikes.models import Bike, BikeStatus
from apps.commands.models import Command, CommandStatus
from apps.rides.models import Ride, RideStatus
from apps.stations.models import Dock, DockState, Station
from apps.stations.services import reconcile_telemetry
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
