from django.conf import settings
from django.db import models

from apps.common.models import TimeStampedModel


class PricingPlan(TimeStampedModel):
    """
    Stores the active pricing configuration.
    Never edit an existing plan — create a new one with a future effective_from.
    Only one plan is active at a time (is_active=True).
    """

    unlock_fee = models.DecimalField(max_digits=10, decimal_places=2)
    per_minute_rate = models.DecimalField(max_digits=10, decimal_places=2)
    minimum_balance = models.DecimalField(max_digits=10, decimal_places=2)
    minimum_top_up = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=3, default="ETB")
    is_active = models.BooleanField(default=False)
    effective_from = models.DateTimeField()

    class Meta:
        db_table = "pricing_plans"
        ordering = ["-effective_from"]

    def __str__(self):
        return (
            f"PricingPlan(unlock={self.unlock_fee}, "
            f"per_min={self.per_minute_rate}, "
            f"active={self.is_active})"
        )


class Wallet(TimeStampedModel):
    """
    One wallet per user. Balance can go negative — negative balance is debt.
    Debt below settings.DEBT_THRESHOLD rolls silently into the next ride.
    Debt at or above threshold blocks unlock until topped up.
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="wallet",
    )
    balance = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    class Meta:
        db_table = "wallets"

    def __str__(self):
        return f"Wallet({self.user.phone}, balance={self.balance})"


class TransactionType(models.TextChoices):
    TOP_UP = "TOP_UP", "Top Up"
    UNLOCK_FEE = "UNLOCK_FEE", "Unlock Fee"
    RIDE_CHARGE = "RIDE_CHARGE", "Ride Charge"
    REFUND = "REFUND", "Refund"


class Transaction(TimeStampedModel):
    """
    Immutable ledger of every wallet movement.
    Never edit a transaction — only append new ones.
    amount is positive for credits (TOP_UP, REFUND) and negative for debits.
    """

    wallet = models.ForeignKey(
        Wallet,
        on_delete=models.PROTECT,
        related_name="transactions",
    )
    type = models.CharField(max_length=20, choices=TransactionType.choices)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    balance_after = models.DecimalField(max_digits=12, decimal_places=2)
    reference = models.CharField(max_length=100, blank=True)
    pricing_plan = models.ForeignKey(
        PricingPlan,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="transactions",
    )

    class Meta:
        db_table = "transactions"
        ordering = ["-created_at"]

    def __str__(self):
        return (
            f"Transaction({self.type}, {self.amount}, "
            f"balance_after={self.balance_after})"
        )


class TopUpMethod(models.TextChoices):
    CHAPA = "CHAPA", "Chapa"
    TELEBIRR = "TELEBIRR", "Telebirr"


class TopUpStatus(models.TextChoices):
    PENDING = "PENDING", "Pending"
    COMPLETED = "COMPLETED", "Completed"
    FAILED = "FAILED", "Failed"


class TopUp(TimeStampedModel):
    """
    Tracks each top-up attempt from initiation through webhook confirmation.
    external_reference is the transaction ID from Chapa/Telebirr.
    """

    wallet = models.ForeignKey(
        Wallet,
        on_delete=models.PROTECT,
        related_name="topups",
    )
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    method = models.CharField(max_length=20, choices=TopUpMethod.choices)
    status = models.CharField(
        max_length=20,
        choices=TopUpStatus.choices,
        default=TopUpStatus.PENDING,
    )
    external_reference = models.CharField(max_length=200, blank=True)
    payment_url = models.URLField(blank=True)

    class Meta:
        db_table = "topups"
        ordering = ["-created_at"]

    def __str__(self):
        return (
            f"TopUp({self.method}, {self.amount} {self.wallet.user.phone}, "
            f"status={self.status})"
        )
