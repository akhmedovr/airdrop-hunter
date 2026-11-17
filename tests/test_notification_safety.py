"""Notification-channel safety tests."""

import unittest
from unittest.mock import patch

from src.core import notifier


class NotificationSafetyTests(unittest.TestCase):
    def test_legacy_telegram_delivery_is_disabled_by_default(self):
        with patch.object(notifier.settings, "LEGACY_TELEGRAM_NOTIFICATIONS_ENABLED", False):
            with patch.object(notifier.settings, "TELEGRAM_BOT_TOKEN", "test-token"):
                with patch.object(notifier.settings, "TELEGRAM_CHAT_ID", "12345"):
                    self.assertFalse(notifier.is_notifier_ready())


if __name__ == "__main__":
    unittest.main()
