from django.urls import path

from apps.payments.views import InitiateTopUpView, chapa_webhook

urlpatterns = [
    path("topup/initiate/", InitiateTopUpView.as_view()),
    path("webhook/chapa/", chapa_webhook),
]
