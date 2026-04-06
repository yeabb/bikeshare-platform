from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.payments.models import Transaction
from apps.payments.services import get_active_pricing_plan, get_or_create_wallet
from apps.rides.models import Ride, RideStatus
from apps.rides.serializers import RideSerializer


class ActiveRideView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            ride = (
                request.user.rides.select_related(
                    "bike", "start_station", "start_dock", "end_station", "end_dock"
                )
                .get(status=RideStatus.ACTIVE)
            )
        except Ride.DoesNotExist:
            return Response({"error": "NO_ACTIVE_RIDE"}, status=404)

        return Response(RideSerializer(ride).data)


class RideListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        rides = request.user.rides.select_related(
            "bike", "start_station", "start_dock", "end_station", "end_dock"
        ).order_by("-started_at")

        return Response({"rides": RideSerializer(rides, many=True).data})


class RideDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, ride_id):
        try:
            ride = request.user.rides.select_related(
                "bike", "start_station", "start_dock", "end_station", "end_dock"
            ).get(ride_id=ride_id)
        except Ride.DoesNotExist:
            return Response({"error": "NOT_FOUND"}, status=404)

        return Response(RideSerializer(ride).data)


class WalletView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        wallet = get_or_create_wallet(request.user)

        try:
            plan = get_active_pricing_plan()
            minimum_balance = str(plan.minimum_balance)
            currency = plan.currency
        except ValueError:
            minimum_balance = None
            currency = "ETB"

        recent_transactions = wallet.transactions.order_by("-created_at")[:10]

        return Response({
            "balance": str(wallet.balance),
            "currency": currency,
            "minimum_balance": minimum_balance,
            "transactions": [
                {
                    "id": str(tx.pk),
                    "type": tx.type,
                    "amount": str(tx.amount),
                    "balance_after": str(tx.balance_after),
                    "reference": tx.reference,
                    "created_at": tx.created_at.isoformat(),
                }
                for tx in recent_transactions
            ],
        })


class TransactionListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        wallet = get_or_create_wallet(request.user)
        transactions = wallet.transactions.order_by("-created_at")

        return Response({
            "transactions": [
                {
                    "id": str(tx.pk),
                    "type": tx.type,
                    "amount": str(tx.amount),
                    "balance_after": str(tx.balance_after),
                    "reference": tx.reference,
                    "created_at": tx.created_at.isoformat(),
                }
                for tx in transactions
            ],
        })
