import hashlib
import hmac
import json
import logging

from django.conf import settings
from django.db import transaction
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.http import JsonResponse
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.payments.chapa import ChapaError, initialize_payment, verify_transaction
from apps.payments.models import TopUp, TopUpMethod, TopUpStatus, TransactionType
from apps.payments.serializers import InitiateTopUpSerializer
from apps.payments.services import credit_wallet, get_active_pricing_plan, get_or_create_wallet

logger = logging.getLogger(__name__)


class InitiateTopUpView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = InitiateTopUpSerializer(data=request.data)
        if not serializer.is_valid():
            return Response({"error": "INVALID_REQUEST", "detail": serializer.errors}, status=400)

        amount = serializer.validated_data["amount"]

        try:
            plan = get_active_pricing_plan()
        except ValueError:
            return Response({"error": "SERVICE_UNAVAILABLE", "detail": "No pricing plan configured."}, status=503)

        if amount < plan.minimum_top_up:
            return Response(
                {
                    "error": "AMOUNT_TOO_LOW",
                    "detail": f"Minimum top-up is {plan.minimum_top_up} {plan.currency}.",
                },
                status=400,
            )

        wallet = get_or_create_wallet(request.user)

        topup = TopUp.objects.create(
            wallet=wallet,
            amount=amount,
            method=TopUpMethod.CHAPA,
            status=TopUpStatus.PENDING,
        )

        callback_url = request.build_absolute_uri(f"/api/v1/payments/webhook/chapa/")
        return_url = f"bikeshare://wallet/topup/complete?topup_id={topup.pk}"

        try:
            checkout_url = initialize_payment(
                tx_ref=str(topup.pk),
                amount=amount,
                phone=request.user.phone,
                callback_url=callback_url,
                return_url=return_url,
            )
        except ChapaError as e:
            topup.status = TopUpStatus.FAILED
            topup.save(update_fields=["status", "updated_at"])
            logger.error("Chapa init failed for topup=%s: %s", topup.pk, e)
            return Response({"error": "PAYMENT_INIT_FAILED", "detail": "Could not reach payment provider."}, status=502)

        topup.payment_url = checkout_url
        topup.external_reference = str(topup.pk)
        topup.save(update_fields=["payment_url", "external_reference", "updated_at"])

        return Response(
            {
                "topup_id": str(topup.pk),
                "amount": str(topup.amount),
                "currency": plan.currency,
                "payment_url": checkout_url,
            },
            status=201,
        )


@csrf_exempt
@require_POST
def chapa_webhook(request):
    """
    Chapa calls this URL when a payment completes.
    Verifies signature, then credits the wallet if the transaction is confirmed.
    Idempotent: safe to call multiple times for the same TopUp.
    """
    # 1. Verify webhook signature
    signature = request.headers.get("Chapa-Signature", "")
    webhook_secret = settings.CHAPA_WEBHOOK_SECRET

    if webhook_secret:
        expected = hmac.new(
            webhook_secret.encode(),
            request.body,
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(expected, signature):
            logger.warning("Chapa webhook signature mismatch")
            return JsonResponse({"error": "Invalid signature"}, status=400)

    # 2. Parse payload
    try:
        payload = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    tx_ref = payload.get("tx_ref") or payload.get("trx_ref")
    if not tx_ref:
        logger.warning("Chapa webhook missing tx_ref: %s", payload)
        return JsonResponse({"error": "Missing tx_ref"}, status=400)

    # 3. Look up TopUp — select_for_update prevents concurrent double-credits
    try:
        with transaction.atomic():
            topup = TopUp.objects.select_for_update().get(pk=tx_ref)

            if topup.status == TopUpStatus.COMPLETED:
                logger.info("Chapa webhook duplicate for topup=%s — ignoring", tx_ref)
                return JsonResponse({"status": "ok"})

            if topup.status == TopUpStatus.FAILED:
                logger.warning("Chapa webhook for already-failed topup=%s — ignoring", tx_ref)
                return JsonResponse({"status": "ok"})

            # 4. Verify with Chapa before crediting
            try:
                confirmed = verify_transaction(tx_ref)
            except ChapaError:
                # Don't fail the webhook — Chapa will retry
                return JsonResponse({"error": "Could not verify transaction"}, status=502)

            if not confirmed:
                logger.warning("Chapa verify returned non-success for tx_ref=%s", tx_ref)
                topup.status = TopUpStatus.FAILED
                topup.save(update_fields=["status", "updated_at"])
                return JsonResponse({"status": "ok"})

            # 5. Credit the wallet
            credit_wallet(
                wallet=topup.wallet,
                amount=topup.amount,
                transaction_type=TransactionType.TOP_UP,
                reference=str(topup.pk),
            )

            topup.status = TopUpStatus.COMPLETED
            topup.save(update_fields=["status", "updated_at"])

            logger.info(
                "Chapa payment completed topup=%s amount=%s wallet=%s",
                topup.pk, topup.amount, topup.wallet_id,
            )

    except TopUp.DoesNotExist:
        logger.warning("Chapa webhook for unknown tx_ref=%s", tx_ref)
        return JsonResponse({"error": "TopUp not found"}, status=404)

    return JsonResponse({"status": "ok"})
