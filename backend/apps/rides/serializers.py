from rest_framework import serializers

from apps.rides.models import Ride


class RideSerializer(serializers.ModelSerializer):
    ride_id = serializers.UUIDField()
    bike_id = serializers.CharField(source="bike_id")
    start_station_id = serializers.CharField(source="start_station_id")
    start_dock_index = serializers.IntegerField(source="start_dock.dock_index")
    end_station_id = serializers.CharField(source="end_station_id", allow_null=True)
    end_dock_index = serializers.SerializerMethodField()
    duration_sec = serializers.SerializerMethodField()

    class Meta:
        model = Ride
        fields = [
            "ride_id",
            "bike_id",
            "start_station_id",
            "start_dock_index",
            "end_station_id",
            "end_dock_index",
            "started_at",
            "ended_at",
            "status",
            "duration_sec",
        ]

    def get_end_dock_index(self, obj):
        return obj.end_dock.dock_index if obj.end_dock else None

    def get_duration_sec(self, obj):
        if obj.ended_at and obj.started_at:
            return int((obj.ended_at - obj.started_at).total_seconds())
        return None
