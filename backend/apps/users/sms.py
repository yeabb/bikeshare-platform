import logging

import boto3
from django.conf import settings

logger = logging.getLogger(__name__)


def send_otp_sms(phone: str, otp: str) -> bool:
    """
    Send OTP via AWS SNS SMS.

    Phone must be in E.164 format (e.g. "+12345678900").
    In production, credentials come from the ECS task role — no key/secret needed.
    Returns True on success, False on any failure.
    """
    try:
        sns = boto3.client("sns", region_name=getattr(settings, "AWS_REGION", "us-east-1"))
        sns.publish(
            PhoneNumber=phone,
            Message=(
                f"Your Bikeshare verification code is {otp}. "
                "Valid for 10 minutes. Do not share this code."
            ),
            MessageAttributes={
                # Transactional = higher priority, not subject to quiet hours.
                # Required for time-sensitive messages like OTPs.
                "AWS.SNS.SMS.SMSType": {
                    "DataType": "String",
                    "StringValue": "Transactional",
                }
            },
        )
        logger.info("OTP SMS dispatched to %s", phone)
        return True
    except Exception:
        logger.exception("Failed to send OTP SMS to %s", phone)
        return False
