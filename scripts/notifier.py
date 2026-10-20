"""
Notification system for the KG Catalog data pipeline.

Provides a pluggable Notifier interface with two built-in backends:
  - LogNotifier   : logs every event to stdout (always active)
  - WebhookNotifier: POSTs a JSON payload to a URL read from an env var

Usage:
    from notifier import get_notifier
    notifier = get_notifier()
    notifier.notify("KG_UNAVAILABLE", {...})
"""

import json
import logging
import os
from abc import ABC, abstractmethod
from datetime import datetime, timezone

import requests

logger = logging.getLogger(__name__)


KG_UNAVAILABLE = "KG_UNAVAILABLE"
NEW_KG_VERSION = "NEW_KG_VERSION"


class Notifier(ABC):
    """Abstract base for notification backends."""

    @abstractmethod
    def notify(self, event_type, payload):
        """
        Send a notification.

        Parameters
        ----------
        event_type : str
            One of KG_UNAVAILABLE or NEW_KG_VERSION.
        payload : dict
            Event-specific data.  Always includes ``timestamp``.
        """


class LogNotifier(Notifier):
    """Prints structured notifications to stdout."""

    def notify(self, event_type, payload):
        timestamp = payload.get("timestamp", _now_iso())
        print(
            f"[NOTIFICATION] [{timestamp}] {event_type}: "
            f"{json.dumps(payload, indent=2, default=str)}"
        )


WEBHOOK_TIMEOUT_SECONDS = 15


class WebhookNotifier(Notifier):
    """
    Sends a JSON payload via HTTP POST.

    The target URL is read from the ``NOTIFICATION_WEBHOOK_URL``
    environment variable.  An optional ``NOTIFICATION_WEBHOOK_SECRET``
    is sent in an ``X-Webhook-Secret`` header when present.
    """

    def __init__(self, url, secret=None):
        self.url = url
        self.secret = secret

    def notify(self, event_type, payload):
        if self.secret and not self.url.lower().startswith("https://"):
            print(
                "[NOTIFICATION] Webhook delivery failed: "
                "HTTPS is required when a webhook secret is configured"
            )
            return

        body = {
            "event": event_type,
            "payload": payload,
        }

        headers = {"Content-Type": "application/json"}
        if self.secret:
            headers["X-Webhook-Secret"] = self.secret

        try:
            resp = requests.post(
                self.url,
                json=body,
                headers=headers,
                timeout=WEBHOOK_TIMEOUT_SECONDS,
            )
            resp.raise_for_status()
            print(f"[NOTIFICATION] Webhook delivered ({resp.status_code})")
        except requests.RequestException as exc:
            print(f"[NOTIFICATION] Webhook delivery failed: {exc}")


class CompositeNotifier(Notifier):
    """Delegates to a list of notifiers, catching per-backend errors."""

    def __init__(self, notifiers):
        self.notifiers = list(notifiers)

    def notify(self, event_type, payload):
        for n in self.notifiers:
            try:
                n.notify(event_type, payload)
            except Exception as exc:
                print(
                    f"[NOTIFICATION] Backend {n.__class__.__name__} "
                    f"failed: {exc}"
                )


def get_notifier():
    """
    Build the notifier stack from environment variables.

    Always includes a ``LogNotifier``.  When the
    ``NOTIFICATION_WEBHOOK_URL`` env var is set, a
    ``WebhookNotifier`` is added.
    """
    backends = [LogNotifier()]

    webhook_url = os.environ.get("NOTIFICATION_WEBHOOK_URL")
    if webhook_url:
        secret = os.environ.get("NOTIFICATION_WEBHOOK_SECRET")
        backends.append(WebhookNotifier(webhook_url, secret=secret))

    if len(backends) == 1:
        return backends[0]

    return CompositeNotifier(backends)


def _now_iso():
    """Return the current UTC time as an ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()


def build_kg_unavailable_payload(kg_name, url, error, status_code=None):
    """
    Build a ``KG_UNAVAILABLE`` notification payload.

    Parameters
    ----------
    kg_name : str
        Human-readable KG identifier (e.g. ``"dblp"``).
    url : str
        The failing distribution URL.
    error : str
        Error description or exception message.
    status_code : int or None
        HTTP status code, if available.
    """
    payload = {
        "kg_name": kg_name,
        "url": url,
        "error": error,
        "timestamp": _now_iso(),
    }
    if status_code is not None:
        payload["status_code"] = status_code
    return payload


def build_new_version_payload(kg_name, old_version, new_version, release_url=None):
    """
    Build a ``NEW_KG_VERSION`` notification payload.

    Parameters
    ----------
    kg_name : str
        Human-readable KG identifier.
    old_version : str
        Previously cataloged version string.
    new_version : str
        Newly detected version string.
    release_url : str or None
        Link to the new release, if available.
    """
    payload = {
        "kg_name": kg_name,
        "old_version": str(old_version),
        "new_version": str(new_version),
        "timestamp": _now_iso(),
    }
    if release_url:
        payload["release_url"] = release_url
    return payload
