
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


EXPO_BATCH_SIZE = 100  # Expo accepts at most 100 messages per request


def send_push_bulk(tokens, title, message, data=None):
    """Send one message to many Expo push tokens, 100 per HTTP request.

    Much faster than ``send_push_to_user`` for broadcasts (one request per 100
    devices instead of one per device). "accepted" means Expo accepted the
    message for delivery, not that the phone has received it.
    """
    summary = {"attempted": 0, "accepted": 0, "failed": 0, "errors": []}
    tokens = list(dict.fromkeys(tokens))  # de-duplicate, keep order

    for start in range(0, len(tokens), EXPO_BATCH_SIZE):
        chunk = tokens[start:start + EXPO_BATCH_SIZE]
        summary["attempted"] += len(chunk)
        payload = [
            {
                "to": token,
                "title": title,
                "body": message,
                "sound": "default",
                "priority": "high",
                "channelId": "general",
                "data": data or {},
            }
            for token in chunk
        ]
        try:
            response = requests.post(
                EXPO_PUSH_URL,
                json=payload,
                headers={"Accept": "application/json"},
                timeout=15,
            )
            response.raise_for_status()
            tickets = response.json().get("data", [])
        except (requests.RequestException, ValueError):
            logger.exception("Expo push batch failed (%s messages)", len(chunk))
            summary["failed"] += len(chunk)
            summary["errors"].append("A batch could not be submitted to the push service.")
            continue

        accepted = sum(1 for t in tickets if isinstance(t, dict) and t.get("status") == "ok")
        summary["accepted"] += accepted
        summary["failed"] += len(chunk) - accepted

    return summary
