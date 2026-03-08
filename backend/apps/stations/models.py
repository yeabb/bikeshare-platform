from django.db import models

from apps.common.models import TimeStampedModel


class StationStatus(models.TextChoices):
    ACTIVE = "ACTIVE", "Active"
    INACTIVE = "INACTIVE", "Inactive"
    MAINTENANCE = "MAINTENANCE", "Maintenance"


class Station(TimeStampedModel):
    # String PK (e.g. "S001") — matches the station ID used in MQTT topics
    id = models.CharField(max_length=20, primary_key=True)
    name = models.CharField(max_length=100)
    lat = models.DecimalField(max_digits=10, decimal_places=7)
    lng = models.DecimalField(max_digits=10, decimal_places=7)
    status = models.CharField(
        max_length=20, choices=StationStatus.choices, default=StationStatus.ACTIVE
    )
    total_docks = models.IntegerField(default=0)

    class Meta:
        db_table = "stations"

    def __str__(self):
        return f"{self.id}: {self.name}"


class DockState(models.TextChoices):
    AVAILABLE = "AVAILABLE", "Available"
    OCCUPIED = "OCCUPIED", "Occupied"
    UNLOCKING = "UNLOCKING", "Unlocking"
    FAULT = "FAULT", "Fault"


class Dock(TimeStampedModel):
    # Auto PK. dock_index is the 1-based integer used in MQTT (dockId field).
    station = models.ForeignKey(Station, on_delete=models.PROTECT, related_name="docks")
    dock_index = models.IntegerField()  # 1-based, matches MQTT dockId
    state = models.CharField(
        max_length=20, choices=DockState.choices, default=DockState.AVAILABLE
    )
    # current_bike is the source of truth for which bike occupies this dock.
    # Bike.current_dock mirrors this for fast lookup. Both are updated atomically.
    current_bike = models.ForeignKey(
        "bikes.Bike",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="docked_at",
    )
    fault_code = models.CharField(max_length=50, blank=True)

    class Meta:
        db_table = "docks"
        unique_together = [("station", "dock_index")]

    @property
    def display_id(self):
        """Human-readable dock ID for API responses, e.g. 'S001-D01'."""
        return f"{self.station_id}-D{self.dock_index:02d}"

    def __str__(self):
        return self.display_id
