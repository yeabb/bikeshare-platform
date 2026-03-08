import uuid

from django.db import models

from apps.common.models import TimeStampedModel


class RideStatus(models.TextChoices):
    ACTIVE = "ACTIVE", "Active"
    COMPLETED = "COMPLETED", "Completed"
    FAILED = "FAILED", "Failed"


class Ride(TimeStampedModel):
    ride_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey("users.User", on_delete=models.PROTECT, related_name="rides")
    bike = models.ForeignKey("bikes.Bike", on_delete=models.PROTECT, related_name="rides")
    # 1:1 with the command that started this ride
    unlock_command = models.OneToOneField(
        "commands.Command",
        on_delete=models.PROTECT,
        related_name="ride",
    )
    start_station = models.ForeignKey(
        "stations.Station", on_delete=models.PROTECT, related_name="rides_started"
    )
    start_dock = models.ForeignKey(
        "stations.Dock", on_delete=models.PROTECT, related_name="rides_started"
    )
    end_station = models.ForeignKey(
        "stations.Station",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="rides_ended",
    )
    end_dock = models.ForeignKey(
        "stations.Dock",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="rides_ended",
    )
    started_at = models.DateTimeField()
    ended_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(
        max_length=20, choices=RideStatus.choices, default=RideStatus.ACTIVE
    )

    class Meta:
        db_table = "rides"

    def __str__(self):
        return f"Ride {self.ride_id} [{self.status}]"
