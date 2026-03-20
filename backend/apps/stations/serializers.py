from rest_framework import serializers

from apps.stations.models import Dock, DockState, Station
from apps.bikes.models import BikeStatus


class DockSerializer(serializers.ModelSerializer):
    dock_id = serializers.SerializerMethodField()
    bike_id = serializers.CharField(source="current_bike.id", allow_null=True, default=None)

    class Meta:
        model = Dock
        fields = ["dock_id", "dock_index", "state", "bike_id"]

    def get_dock_id(self, obj):
        return obj.display_id


class StationStateSerializer(serializers.ModelSerializer):
    station_id = serializers.CharField(source="id")
    docks = DockSerializer(many=True)

    class Meta:
        model = Station
        fields = ["station_id", "name", "status", "lat", "lng", "docks"]


class StationSummarySerializer(serializers.ModelSerializer):
    """
    Lightweight serializer for the station list endpoint.
    Returns only what the map pins and list cards need — no dock details.
    available_bikes and open_docks are computed from dock states.
    """
    station_id = serializers.CharField(source="id")
    available_bikes = serializers.SerializerMethodField()
    open_docks = serializers.SerializerMethodField()
    bike_ids = serializers.SerializerMethodField()

    class Meta:
        model = Station
        fields = ["station_id", "name", "lat", "lng", "status", "available_bikes", "open_docks", "bike_ids"]

    def get_available_bikes(self, obj):
        return sum(
            1 for dock in obj.docks.all()
            if dock.current_bike is not None and dock.current_bike.status == BikeStatus.AVAILABLE
        )

    def get_open_docks(self, obj):
        return sum(
            1 for dock in obj.docks.all()
            if dock.state == DockState.AVAILABLE and dock.current_bike is None
        )

    def get_bike_ids(self, obj):
        return [
            dock.current_bike.id for dock in obj.docks.all()
            if dock.current_bike is not None and dock.current_bike.status == BikeStatus.AVAILABLE
        ]


class InactiveStationSerializer(serializers.ModelSerializer):
    station_id = serializers.CharField(source="id")

    class Meta:
        model = Station
        fields = ["station_id", "name", "lat", "lng", "last_telemetry_at", "created_at"]
