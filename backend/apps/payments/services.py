import logging
from decimal import Decimal

from django.conf import settings
from django.db import transaction

from apps.payments.models import PricingPlan, Transaction, TransactionType, Wallet

logger = logging.getLogger(__name__)


class InsufficientBalanceError(Exception):
    """Raised when a debit would push balance below the allowed debt threshold."""
    pass


class WalletNotFoundError(Exception):
    pass


def get_active_pricing_plan() -> PricingPlan:
    """Return the currently active pricing plan. Raises if none is configured."""
    plan = PricingPlan.objects.filter(is_active=True).first()
    if plan is None:
        raise ValueError("No active pricing plan configured.")
    return plan


def get_or_create_wallet(user) -> Wallet:
    wallet, _ = Wallet.objects.get_or_create(user=user)
    return wallet


def credit_wallet(
    wallet: Wallet,
    amount: Decimal,
    transaction_type: str,
    reference: str = "",
    pricing_plan: PricingPlan = None,
) -> Transaction:
    """
    Add funds to a wallet. amount must be positive.
    Returns the created Transaction. Runs inside a select_for_update lock.
    """
    if amount <= 0:
        raise ValueError(f"Credit amount must be positive, got {amount}")

    with transaction.atomic():
        wallet = Wallet.objects.select_for_update().get(pk=wallet.pk)
        wallet.balance += amount
        wallet.save(update_fields=["balance", "updated_at"])

        tx = Transaction.objects.create(
            wallet=wallet,
            type=transaction_type,
            amount=amount,
            balance_after=wallet.balance,
            reference=reference,
            pricing_plan=pricing_plan,
        )

    logger.info(
        f"Wallet {wallet.pk} credited {amount} ({transaction_type}) "
        f"— balance_after={wallet.balance} ref={reference}"
    )
    return tx


def debit_wallet(
    wallet: Wallet,
    amount: Decimal,
    transaction_type: str,
    reference: str = "",
    pricing_plan: PricingPlan = None,
) -> Transaction:
    """
    Deduct funds from a wallet. amount must be positive (stored as negative in ledger).
    Raises InsufficientBalanceError if the resulting balance would hit or exceed
    the debt threshold defined in settings.DEBT_THRESHOLD.
    Returns the created Transaction. Runs inside a select_for_update lock.
    """
    if amount <= 0:
        raise ValueError(f"Debit amount must be positive, got {amount}")

    debt_threshold = Decimal(str(settings.DEBT_THRESHOLD))

    with transaction.atomic():
        wallet = Wallet.objects.select_for_update().get(pk=wallet.pk)
        new_balance = wallet.balance - amount

        if new_balance <= -debt_threshold:
            raise InsufficientBalanceError(
                f"Debit of {amount} would bring balance to {new_balance}, "
                f"which hits or exceeds the debt threshold of {debt_threshold}."
            )

        wallet.balance = new_balance
        wallet.save(update_fields=["balance", "updated_at"])

        tx = Transaction.objects.create(
            wallet=wallet,
            type=transaction_type,
            amount=-amount,  # negative in ledger
            balance_after=wallet.balance,
            reference=reference,
            pricing_plan=pricing_plan,
        )

    logger.info(
        f"Wallet {wallet.pk} debited {amount} ({transaction_type}) "
        f"— balance_after={wallet.balance} ref={reference}"
    )
    return tx


def can_unlock(wallet: Wallet, pricing_plan: PricingPlan) -> tuple[bool, str]:
    """
    Check if a user is allowed to unlock a bike.
    Returns (True, "") if allowed, or (False, reason_code) if not.

    Rules:
    - Balance must be >= -DEBT_THRESHOLD (debt below threshold rolls silently)
    - Balance must be >= minimum_balance set in the pricing plan
    """
    debt_threshold = Decimal(str(settings.DEBT_THRESHOLD))

    if wallet.balance <= -debt_threshold:
        return False, "DEBT_THRESHOLD_EXCEEDED"

    if wallet.balance < pricing_plan.minimum_balance:
        return False, "INSUFFICIENT_BALANCE"

    return True, ""
