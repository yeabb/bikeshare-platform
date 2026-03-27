from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView

from apps.users.views import RequestOTPView, UpdateProfileView, VerifyOTPView

urlpatterns = [
    path("request-otp/", RequestOTPView.as_view()),
    path("verify-otp/", VerifyOTPView.as_view()),
    path("token/refresh/", TokenRefreshView.as_view()),
    path("me/", UpdateProfileView.as_view()),
]
