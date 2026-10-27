
from rest_framework import serializers, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import DevicePushToken


class PushTokenSerializer(serializers.ModelSerializer):
    class Meta:
        model = DevicePushToken
        fields = ["token", "platform"]

    def validate_token(self, value):
        if not value.startswith("ExponentPushToken[") and not value.startswith(
            "ExpoPushToken["
        ):
            raise serializers.ValidationError(
                "A valid Expo push token is required."
            )
        return value


class RegisterPushTokenView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = PushTokenSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        token = serializer.validated_data["token"]
        platform = serializer.validated_data["platform"]

        # If this device token previously belonged to another account,
        # transfer it to the currently authenticated account.
        device, _ = DevicePushToken.objects.update_or_create(
            token=token,
            defaults={
                "user": request.user,
                "platform": platform,
            },
        )

        return Response(
            {
                "registered": True,
                "id": device.pk,
            },
            status=status.HTTP_200_OK,
        )
