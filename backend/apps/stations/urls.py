from django.urls import path

from apps.stations.views import InactiveStationsView, StationStateView

urlpatterns = [
    path("inactive", InactiveStationsView.as_view()),
    path("<str:station_id>/state", StationStateView.as_view()),
]
