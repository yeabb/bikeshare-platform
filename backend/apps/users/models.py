import uuid

from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models

from apps.common.models import TimeStampedModel


class UserManager(BaseUserManager):
    def create_user(self, phone, **extra_fields):
        if not phone:
            raise ValueError("Phone is required")
        user = self.model(phone=phone, **extra_fields)
        user.set_unusable_password()
        user.save(using=self._db)
        return user

    def create_superuser(self, phone, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        user = self.create_user(phone, **extra_fields)
        if password:
            user.set_password(password)
            user.save(using=self._db)
        return user


class UserStatus(models.TextChoices):
    ACTIVE = "ACTIVE", "Active"
    SUSPENDED = "SUSPENDED", "Suspended"
    PENDING_VERIFICATION = "PENDING_VERIFICATION", "Pending Verification"


class User(AbstractBaseUser, PermissionsMixin, TimeStampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    phone = models.CharField(max_length=20, unique=True)
    email = models.EmailField(blank=True)
    status = models.CharField(
        max_length=30,
        choices=UserStatus.choices,
        default=UserStatus.PENDING_VERIFICATION,
    )
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)

    # OTP fields — SMS delivery is stubbed; in DEBUG mode OTP is returned in response
    otp_code = models.CharField(max_length=6, blank=True)
    otp_expires_at = models.DateTimeField(null=True, blank=True)

    USERNAME_FIELD = "phone"
    REQUIRED_FIELDS = []

    objects = UserManager()

    class Meta:
        db_table = "users"

    def __str__(self):
        return self.phone
