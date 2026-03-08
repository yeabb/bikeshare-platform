from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

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
