from django.urls import path

from apps.stations.views import StationStateView

urlpatterns = [
    path("<str:station_id>/state", StationStateView.as_view()),
]
