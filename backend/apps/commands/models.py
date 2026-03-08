import uuid

from django.db import models

from apps.common.models import TimeStampedModel


class CommandType(models.TextChoices):
    UNLOCK = "UNLOCK", "Unlock"


class CommandStatus(models.TextChoices):
    PENDING = "PENDING", "Pending"
    SUCCESS = "SUCCESS", "Success"
    FAILED = "FAILED", "Failed"
    TIMEOUT = "TIMEOUT", "Timeout"


class Command(TimeStampedModel):
    request_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    type = models.CharField(max_length=20, choices=CommandType.choices, default=CommandType.UNLOCK)
    user = models.ForeignKey("users.User", on_delete=models.PROTECT, related_name="commands")
    station = models.ForeignKey(
        "stations.Station", on_delete=models.PROTECT, related_name="commands"
    )
    dock = models.ForeignKey(
        "stations.Dock", on_delete=models.PROTECT, related_name="commands"
    )
    bike = models.ForeignKey(
        "bikes.Bike",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="commands",
    )
    status = models.CharField(
        max_length=20, choices=CommandStatus.choices, default=CommandStatus.PENDING
    )
    failure_reason = models.CharField(max_length=100, blank=True)
    published_at = models.DateTimeField(null=True, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    # Commands not resolved by expires_at are swept to TIMEOUT by a background job
    expires_at = models.DateTimeField()

    class Meta:
        db_table = "commands"

    def __str__(self):
        return f"Command {self.request_id} [{self.status}]"
