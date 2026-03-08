from django.db import models

from apps.common.models import TimeStampedModel


class BikeStatus(models.TextChoices):
    AVAILABLE = "AVAILABLE", "Available"
    IN_USE = "IN_USE", "In Use"
    MAINTENANCE = "MAINTENANCE", "Maintenance"
    LOST = "LOST", "Lost"


class Bike(TimeStampedModel):
    # String PK (e.g. "B742") — matches the bike ID in QR codes and MQTT payloads
    id = models.CharField(max_length=20, primary_key=True)
    status = models.CharField(
        max_length=20, choices=BikeStatus.choices, default=BikeStatus.AVAILABLE
    )

    # Location fields — denormalized from Dock for fast lookup.
    # Always updated atomically with Dock.current_bike in service calls.
    current_station = models.ForeignKey(
        "stations.Station",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="bikes",
    )
    current_dock = models.ForeignKey(
        "stations.Dock",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="bike",
    )
    # Set when ride is ACTIVE. Cleared on ride completion.
    current_ride = models.ForeignKey(
        "rides.Ride",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )

    class Meta:
        db_table = "bikes"

    def __str__(self):
        return self.id
