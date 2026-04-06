from django.urls import path

from apps.rides.views import ActiveRideView, RideDetailView, RideListView, TransactionListView, WalletView

urlpatterns = [
    path("active-ride/", ActiveRideView.as_view()),
    path("rides/", RideListView.as_view()),
    path("rides/<uuid:ride_id>/", RideDetailView.as_view()),
    path("wallet/", WalletView.as_view()),
    path("wallet/transactions/", TransactionListView.as_view()),
]
