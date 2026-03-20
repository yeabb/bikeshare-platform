from django.urls import path

from apps.commands.views import CommandDetailView, UnlockCommandView

urlpatterns = [
    path("unlock/", UnlockCommandView.as_view()),
    path("<uuid:request_id>/", CommandDetailView.as_view()),
]
