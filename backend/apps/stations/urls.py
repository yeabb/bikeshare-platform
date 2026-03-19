from django.urls import path

from apps.stations.views import InactiveStationsView, StationListView, StationStateView

urlpatterns = [
    path("", StationListView.as_view()),
    path("inactive/", InactiveStationsView.as_view()),
    path("<str:station_id>/state/", StationStateView.as_view()),
]
