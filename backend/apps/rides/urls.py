from django.urls import path

from apps.rides.views import ActiveRideView, RideDetailView, RideListView

urlpatterns = [
    path("active-ride", ActiveRideView.as_view()),
    path("rides", RideListView.as_view()),
    path("rides/<uuid:ride_id>", RideDetailView.as_view()),
]
