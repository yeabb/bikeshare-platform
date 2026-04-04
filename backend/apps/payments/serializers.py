from rest_framework import serializers


class InitiateTopUpSerializer(serializers.Serializer):
    amount = serializers.DecimalField(max_digits=12, decimal_places=2)
