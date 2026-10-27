
import logging

import requests

from .models import DevicePushToken

logger = logging.getLogger(__name__)

EXPO_PUSH_URL = "https://exp.host/--/api/v2/push/send"


def send_push_to_user(user, title, message, data=None):
    devices = DevicePushToken.objects.filter(user=user)

    results = []

    for device in devices.iterator():
        payload = {
            "to": device.token,
            "title": title,
            "body": message,
            "sound": "default",
            "priority": "high",
            "channelId": "general",
            "data": data or {},
        }

        try:
            response = requests.post(
                EXPO_PUSH_URL,
                json=payload,
                headers={"Accept": "application/json"},
                timeout=10,
            )
            response.raise_for_status()
            result = response.json()

            results.append({
                "device_id": device.pk,
                "result": result,
            })

        except requests.RequestException:
            logger.exception(
                "Failed to send push notification to device %s",
                device.pk,
            )
            results.append({
                "device_id": device.pk,
                "error": "Push request failed",
            })

    return results
