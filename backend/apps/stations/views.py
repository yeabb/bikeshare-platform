from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.stations.models import Station
from apps.stations.serializers import StationStateSerializer


class StationStateView(APIView):
    permission_classes = [AllowAny]

    def get(self, request, station_id):
        try:
            station = Station.objects.prefetch_related(
                "docks__current_bike"
            ).get(id=station_id)
        except Station.DoesNotExist:
            return Response({"error": "NOT_FOUND"}, status=404)

        return Response(StationStateSerializer(station).data)
