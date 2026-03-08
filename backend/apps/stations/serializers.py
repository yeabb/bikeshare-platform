from rest_framework import serializers

from apps.stations.models import Dock, Station


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
