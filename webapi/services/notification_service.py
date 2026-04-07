# TradingAgents WebAPI Services - Notification Service
# pyright: reportUnknownParameterType=false, reportMissingParameterType=false, reportUnusedParameter=false, reportUnknownMemberType=false, reportUnknownArgumentType=false, reportMissingTypeStubs=false, reportDeprecated=false, reportUnusedCallResult=false, reportAny=false, reportExplicitAny=false, reportUnannotatedClassAttribute=false

"""
Cross-platform desktop notification service for watchlist monitoring.

Supports:
- Windows: win10toast (ToastNotifier)
- Mac: osascript (AppleScript notifications)
- Linux: notify-send (libnotify)
"""

import logging
import platform
import shutil
import subprocess
from typing import Any, Dict, Tuple

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------
# Platform Detection
# ------------------------------------------------------------------

def get_platform() -> str:
    """Detect the current platform."""
    system = platform.system().lower()
    if system == "windows":
        return "windows"
    elif system == "darwin":
        return "mac"
    elif system == "linux":
        return "linux"
    return "unknown"


PLATFORM = get_platform()


# ------------------------------------------------------------------
# Platform-Specific Notification Implementations
# ------------------------------------------------------------------

class WindowsNotifier:
    """Windows desktop notifier using win10toast."""

    def __init__(self):
        self._toaster = None
        self._init_toaster()

    def _init_toaster(self):
        """Initialize the Windows toast notifier."""
        try:
            from win10toast import ToastNotifier
            self._toaster = ToastNotifier()
            logger.info("[NOTIFICATION] Windows ToastNotifier initialized")
        except ImportError:
            logger.debug("[NOTIFICATION] win10toast not installed, desktop notifications disabled")
            self._toaster = None

    def send(self, title: str, message: str, duration: int = 10, **kwargs) -> bool:
        """
        Send Windows toast notification.

        Args:
            title: Notification title
            message: Notification message
            duration: Display duration in seconds (default 10)
        """
        if not self._toaster:
            logger.warning("[NOTIFICATION] ToastNotifier not available")
            return False

        try:
            self._toaster.show_toast(
                title=title,
                msg=message,
                duration=duration,
                threaded=True,
            )
            logger.info(f"[NOTIFICATION] Windows toast sent: {title}")
            return True
        except Exception as e:
            logger.error(f"[NOTIFICATION] Failed to send Windows toast: {e}")
            return False


class MacNotifier:
    """Mac desktop notifier using osascript."""

    def send(self, title: str, message: str, sound: str = "Glass", **kwargs) -> bool:
        """
        Send Mac notification using AppleScript.

        Args:
            title: Notification title
            message: Notification message
            sound: Sound name (default "Glass")
        """
        try:
            # Escape quotes in title and message
            title_escaped = title.replace('"', '\\"')
            message_escaped = message.replace('"', '\\"')

            script = f'display notification "{message_escaped}" with title "{title_escaped}" sound name "{sound}"'
            subprocess.run(
                ["osascript", "-e", script],
                capture_output=True,
                check=False,
            )
            logger.info(f"[NOTIFICATION] Mac notification sent: {title}")
            return True
        except Exception as e:
            logger.error(f"[NOTIFICATION] Failed to send Mac notification: {e}")
            return False


class LinuxNotifier:
    """Linux desktop notifier using notify-send."""

    def send(self, title: str, message: str, urgency: str = "normal", **kwargs) -> bool:
        """
        Send Linux notification using notify-send.

        Args:
            title: Notification title
            message: Notification message
            urgency: Urgency level - "low", "normal", "critical" (default "normal")
        """
        if shutil.which("notify-send") is None:
            logger.warning("[NOTIFICATION] notify-send not found on PATH")
            return False

        try:
            completed = subprocess.run(
                ["notify-send", "-u", urgency, title, message],
                capture_output=True,
                check=False,
            )
            if completed.returncode != 0:
                logger.warning(
                    "[NOTIFICATION] notify-send exited with %s: %s",
                    completed.returncode,
                    completed.stderr.decode(errors="ignore") if completed.stderr else "",
                )
                return False
            logger.info(f"[NOTIFICATION] Linux notification sent: {title}")
            return True
        except Exception as e:
            logger.error(f"[NOTIFICATION] Failed to send Linux notification: {e}")
            return False


class ConsoleNotifier:
    """Fallback console notifier when no platform-specific implementation is available."""

    def send(self, title: str, message: str, **kwargs) -> bool:
        """Print notification to console."""
        separator = "=" * 50
        try:
            print(f"\n{separator}")
            print(f"[NOTIFICATION] {title}")
            print(f"{message}")
            print(f"{separator}\n")
        except OSError:
            # Ignore console output errors (e.g., when running as service on Windows)
            pass
        logger.info(f"[NOTIFICATION] Console notification: {title}")
        return True


# ------------------------------------------------------------------
# Notification Service
# ------------------------------------------------------------------

class NotificationService:
    """
    Cross-platform desktop notification service.

    Automatically detects platform and uses appropriate notification backend.
    """

    def __init__(self):
        self._notifier = self._create_notifier()
        logger.info(f"[NOTIFICATION] NotificationService initialized for platform: {PLATFORM}")

    def _create_notifier(self):
        """Create the appropriate notifier based on platform."""
        if PLATFORM == "windows":
            return WindowsNotifier()
        elif PLATFORM == "mac":
            return MacNotifier()
        elif PLATFORM == "linux":
            return LinuxNotifier()
        else:
            logger.warning(f"[NOTIFICATION] Unknown platform: {PLATFORM}, using console notifier")
            return ConsoleNotifier()

    def send(self, title: str, message: str, urgency: str = "normal", **kwargs) -> bool:
        """
        Send a desktop notification.

        Args:
            title: Notification title
            message: Notification message
            urgency: Urgency level for Linux ("low", "normal", "critical")
        """
        return bool(self._notifier.send(title, message, urgency=urgency, **kwargs))

    def send_turning_alert(
        self,
        title: str,
        message: str,
        importance: float = 0.5,
        **kwargs
    ) -> bool:
        """
        Send a turning point alert notification.

        Args:
            title: Alert title
            message: Alert message
            importance: Importance score (0-1), affects urgency on Linux
        """
        # Adjust urgency based on importance on Linux
        if PLATFORM == "linux":
            urgency = "critical" if importance > 0.8 else "normal"
        else:
            urgency = "normal"

        return self.send(title, message, urgency=urgency, **kwargs)


# ------------------------------------------------------------------
# Alert Formatting
# ------------------------------------------------------------------

def format_turning_alert(
    symbol: str,
    name: str,
    result: Dict[str, Any],
    reason: str,
    importance: float
) -> Tuple[str, str]:
    """
    Format a turning point alert notification.

    Args:
        symbol: Stock symbol
        name: Stock name
        result: Analysis result dict with signal, confidence, risk_level
        reason: Turning reason string
        importance: Importance score (0-1)

    Returns:
        (title: str, message: str)
    """
    signal = result.get('signal', 'UNKNOWN')
    confidence = result.get('confidence', 0)

    # Signal emoji mapping
    signal_emoji = {
        'BUY': '🟢',
        'SELL': '🔴',
        'HOLD': '🟡'
    }.get(signal, '⚪')

    # Importance indicator
    importance_indicator = '🔥' if importance > 0.9 else '⚡' if importance > 0.7 else '📊'

    # Format title
    title = f"{importance_indicator} 变盘信号 - {name} ({symbol})"

    # Format message
    message = f"{signal_emoji} {signal} (置信度{confidence:.0%})\n📌 {reason}"

    return title, message


def format_analysis_complete(symbol: str, name: str, signal: str, confidence: float) -> Tuple[str, str]:
    """
    Format an analysis complete notification.

    Args:
        symbol: Stock symbol
        name: Stock name
        signal: Signal (BUY/SELL/HOLD)
        confidence: Confidence score (0-1)

    Returns:
        (title: str, message: str)
    """
    signal_emoji = {
        'BUY': '🟢',
        'SELL': '🔴',
        'HOLD': '🟡'
    }.get(signal, '⚪')

    title = f"📊 分析完成 - {name} ({symbol})"
    message = f"{signal_emoji} {signal} (置信度{confidence:.0%})"

    return title, message


# ------------------------------------------------------------------
# Global Singleton Instance
# ------------------------------------------------------------------

notification_service = NotificationService()


# ------------------------------------------------------------------
# Test / Demo
# ------------------------------------------------------------------

if __name__ == "__main__":
    # Test script - send a test notification
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )

    print(f"Detected platform: {PLATFORM}")
    print("Sending test notifications...\n")

    # Test basic notification
    notification_service.send(
        title="Test Notification",
        message="This is a test notification from TradingAgents."
    )

    # Test turning alert
    import time
    time.sleep(1)

    test_result = {
        'signal': 'BUY',
        'confidence': 0.87,
        'risk_level': 'medium',
    }
    title, message = format_turning_alert(
        symbol="000001",
        name="平安银行",
        result=test_result,
        reason="信号转变: SELL → BUY",
        importance=0.95
    )
    notification_service.send_turning_alert(title, message, importance=0.95)

    print("\nTest notifications sent (check your desktop).")
