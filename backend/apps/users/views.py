import random

from django.conf import settings
from django.utils import timezone
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

from apps.users.models import User


class RequestOTPView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        phone = request.data.get("phone")
        if not phone:
            return Response({"error": "MISSING_PHONE"}, status=400)

        otp = _generate_otp()
        expires_at = timezone.now() + timezone.timedelta(minutes=10)

        user, _ = User.objects.get_or_create(phone=phone)
        user.otp_code = otp
        user.otp_expires_at = expires_at
        user.save(update_fields=["otp_code", "otp_expires_at"])

        # TODO: send SMS via SNS or Twilio
        if settings.DEBUG:
            # Return OTP in response for local development only
            return Response({"message": "OTP sent", "otp": otp})
        return Response({"message": "OTP sent"})


class VerifyOTPView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        phone = request.data.get("phone")
        otp = request.data.get("otp")

        if not phone or not otp:
            return Response({"error": "MISSING_FIELDS"}, status=400)

        try:
            user = User.objects.get(phone=phone)
        except User.DoesNotExist:
            return Response({"error": "INVALID_OTP"}, status=400)

        if user.otp_code != otp:
            return Response({"error": "INVALID_OTP"}, status=400)

        if not user.otp_expires_at or timezone.now() > user.otp_expires_at:
            return Response({"error": "OTP_EXPIRED"}, status=400)

        user.otp_code = ""
        user.status = "ACTIVE"
        user.save(update_fields=["otp_code", "status"])

        refresh = RefreshToken.for_user(user)
        return Response(
            {
                "access": str(refresh.access_token),
                "refresh": str(refresh),
                "user": {"id": str(user.id), "phone": user.phone, "name": user.name},
            }
        )


class UpdateProfileView(APIView):
    permission_classes = [IsAuthenticated]

    def patch(self, request):
        name = request.data.get("name", "").strip()
        if not name:
            return Response({"error": "MISSING_NAME"}, status=400)
        request.user.name = name
        request.user.save(update_fields=["name"])
        return Response({"name": name})


def _generate_otp():
    return str(random.randint(100000, 999999))
