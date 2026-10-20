"""
Unit and integration tests for the KG Catalog notification system.

Covers:
  - Notifier construction via get_notifier()
  - WebhookNotifier delivery, secret security over HTTP, and error resilience
  - CompositeNotifier fan-out behavior
  - Payload builder structures
  - Integration with production check_url_and_update_yaml()
  - Integration with production run_daily_check()
"""

import json
import os
import sys
import tempfile
import textwrap
import unittest
from io import StringIO
from unittest.mock import MagicMock, patch

# Ensure the scripts/ directory is importable
sys.path.insert(
    0,
    os.path.join(os.path.dirname(__file__), "..", "scripts"),
)

import requests
import yaml
from check_url_update_yaml import check_url_and_update_yaml
from daily_check import run_daily_check
from notifier import (
    KG_UNAVAILABLE,
    NEW_KG_VERSION,
    CompositeNotifier,
    LogNotifier,
    WebhookNotifier,
    build_kg_unavailable_payload,
    build_new_version_payload,
    get_notifier,
)


# --------------------------------------------------
# LogNotifier
# --------------------------------------------------

class TestLogNotifier(unittest.TestCase):
    """Verify LogNotifier prints structured JSON to stdout."""

    def test_notify_prints_event(self):
        notifier = LogNotifier()
        payload = build_kg_unavailable_payload(
            kg_name="test-kg",
            url="https://example.com/data.nt.gz",
            error="HTTP 404",
            status_code=404,
        )

        captured = StringIO()
        with patch("sys.stdout", captured):
            notifier.notify(KG_UNAVAILABLE, payload)

        output = captured.getvalue()
        self.assertIn("[NOTIFICATION]", output)
        self.assertIn("KG_UNAVAILABLE", output)
        self.assertIn("test-kg", output)
        self.assertIn("404", output)


# --------------------------------------------------
# WebhookNotifier
# --------------------------------------------------

class TestWebhookNotifier(unittest.TestCase):
    """Verify WebhookNotifier POSTs correct JSON and handles failures."""

    @patch("notifier.requests.post")
    def test_successful_delivery(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_post.return_value = mock_resp

        notifier = WebhookNotifier(
            url="https://hooks.example.com/notify",
            secret="s3cret",
        )
        payload = {"kg_name": "dblp", "timestamp": "2026-01-01T00:00:00+00:00"}
        notifier.notify(KG_UNAVAILABLE, payload)

        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        self.assertEqual(args[0], "https://hooks.example.com/notify")
        self.assertEqual(kwargs["json"]["event"], KG_UNAVAILABLE)
        self.assertEqual(kwargs["json"]["payload"]["kg_name"], "dblp")
        self.assertEqual(kwargs["headers"]["X-Webhook-Secret"], "s3cret")
        self.assertEqual(kwargs["timeout"], 15)

    @patch("notifier.requests.post")
    def test_delivery_failure_does_not_raise(self, mock_post):
        """A failing webhook must NEVER crash the caller."""
        mock_post.side_effect = requests.ConnectionError("refused")

        notifier = WebhookNotifier(url="https://hooks.example.com/notify")
        # This must NOT raise
        notifier.notify(KG_UNAVAILABLE, {"kg_name": "broken"})

    @patch("notifier.requests.post")
    def test_http_with_secret_blocks_delivery(self, mock_post):
        """Webhooks configured with a secret must reject insecure HTTP URLs."""
        notifier = WebhookNotifier(
            url="http://hooks.example.com/notify",
            secret="s3cret",
        )
        payload = {"kg_name": "dblp", "timestamp": "2026-01-01T00:00:00+00:00"}
        notifier.notify(KG_UNAVAILABLE, payload)

        mock_post.assert_not_called()

    @patch("notifier.requests.post")
    def test_no_secret_header_when_unset(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_post.return_value = mock_resp

        notifier = WebhookNotifier(url="https://hooks.example.com/notify")
        notifier.notify(NEW_KG_VERSION, {"kg_name": "test"})

        args, kwargs = mock_post.call_args
        self.assertNotIn("X-Webhook-Secret", kwargs["headers"])


# --------------------------------------------------
# CompositeNotifier
# --------------------------------------------------

class TestCompositeNotifier(unittest.TestCase):
    """Verify CompositeNotifier delegates to all sub-notifiers."""

    def test_fan_out(self):
        n1 = MagicMock()
        n2 = MagicMock()
        composite = CompositeNotifier([n1, n2])

        composite.notify(KG_UNAVAILABLE, {"kg_name": "test"})

        n1.notify.assert_called_once()
        n2.notify.assert_called_once()

    def test_one_failing_backend_does_not_stop_others(self):
        n1 = MagicMock()
        n1.notify.side_effect = RuntimeError("Boom")
        n2 = MagicMock()

        composite = CompositeNotifier([n1, n2])
        composite.notify(KG_UNAVAILABLE, {"kg_name": "test"})

        n2.notify.assert_called_once()


# --------------------------------------------------
# Factory: get_notifier()
# --------------------------------------------------

class TestGetNotifier(unittest.TestCase):

    @patch.dict(os.environ, {}, clear=True)
    def test_default_returns_log_notifier(self):
        notifier = get_notifier()
        self.assertIsInstance(notifier, LogNotifier)

    @patch.dict(
        os.environ,
        {"NOTIFICATION_WEBHOOK_URL": "https://example.com/hook"},
        clear=True,
    )
    def test_returns_composite_with_webhook(self):
        notifier = get_notifier()
        self.assertIsInstance(notifier, CompositeNotifier)
        self.assertEqual(len(notifier.notifiers), 2)
        self.assertIsInstance(notifier.notifiers[0], LogNotifier)
        self.assertIsInstance(notifier.notifiers[1], WebhookNotifier)


# --------------------------------------------------
# Payload builders
# --------------------------------------------------

class TestPayloadBuilders(unittest.TestCase):

    def test_kg_unavailable_payload_required_fields(self):
        p = build_kg_unavailable_payload(
            kg_name="wikidata",
            url="https://dumps.wikimedia.org/data.ttl",
            error="HTTP 404",
            status_code=404,
        )
        self.assertEqual(p["kg_name"], "wikidata")
        self.assertEqual(p["url"], "https://dumps.wikimedia.org/data.ttl")
        self.assertEqual(p["error"], "HTTP 404")
        self.assertEqual(p["status_code"], 404)
        self.assertIn("timestamp", p)

    def test_kg_unavailable_payload_no_status_code(self):
        p = build_kg_unavailable_payload(
            kg_name="test",
            url="https://example.com",
            error="Connection refused",
        )
        self.assertNotIn("status_code", p)

    def test_new_version_payload_required_fields(self):
        p = build_new_version_payload(
            kg_name="dblp",
            old_version="2025-10-01",
            new_version="2025-11-01",
            release_url="https://example.com/dblp-2025-11-01.nt.gz",
        )
        self.assertEqual(p["kg_name"], "dblp")
        self.assertEqual(p["old_version"], "2025-10-01")
        self.assertEqual(p["new_version"], "2025-11-01")
        self.assertEqual(p["release_url"], "https://example.com/dblp-2025-11-01.nt.gz")
        self.assertIn("timestamp", p)

    def test_new_version_payload_no_release_url(self):
        p = build_new_version_payload(
            kg_name="test",
            old_version="v1",
            new_version="v2",
        )
        self.assertNotIn("release_url", p)


# --------------------------------------------------
# Integration: Production check_url_and_update_yaml
# --------------------------------------------------

class TestCheckUrlProductionIntegration(unittest.TestCase):
    """
    Test production check_url_and_update_yaml function with mock HTTP requests.
    """

    def _write_yaml(self, tmp_dir, yaml_content):
        kg_dir = os.path.join(tmp_dir, "test-kg")
        os.makedirs(kg_dir, exist_ok=True)
        path = os.path.join(kg_dir, "metadata.yaml")
        with open(path, "w") as f:
            f.write(yaml_content)
        return path

    @patch("check_url_update_yaml.requests.head")
    @patch("check_url_update_yaml.get_notifier")
    def test_active_url_changing_to_error_triggers_kg_unavailable(self, mock_get_notifier, mock_head):
        """Active URL returning HTTP 404 updates status to error and fires KG_UNAVAILABLE."""
        mock_notifier = MagicMock()
        mock_get_notifier.return_value = mock_notifier

        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_head.return_value = mock_resp

        yaml_content = textwrap.dedent("""\
            artifacts:
              - artifact: test-artifact
                versions:
                  - version: "2025-01-01"
                    distributions:
                      - file: https://example.com/dead-link.nt.gz
                        status: active
        """)

        with tempfile.TemporaryDirectory() as tmp:
            yaml_path = self._write_yaml(tmp, yaml_content)

            check_url_and_update_yaml(yaml_path)

            mock_notifier.notify.assert_called_once()
            call_args = mock_notifier.notify.call_args
            self.assertEqual(call_args[0][0], KG_UNAVAILABLE)
            self.assertEqual(call_args[0][1]["kg_name"], "test-kg")
            self.assertEqual(call_args[0][1]["status_code"], 404)
            self.assertIn("dead-link.nt.gz", call_args[0][1]["url"])

            # Verify YAML status was updated to error
            with open(yaml_path, "r") as f:
                updated_data = yaml.safe_load(f)
            dist_status = updated_data["artifacts"][0]["versions"][0]["distributions"][0]["status"]
            self.assertEqual(dist_status, "error")

    @patch("check_url_update_yaml.requests.head")
    @patch("check_url_update_yaml.get_notifier")
    def test_request_timeout_triggers_kg_unavailable(self, mock_get_notifier, mock_head):
        """A network timeout updates status to error and fires KG_UNAVAILABLE."""
        mock_notifier = MagicMock()
        mock_get_notifier.return_value = mock_notifier

        mock_head.side_effect = requests.Timeout("Connection timed out")

        yaml_content = textwrap.dedent("""\
            artifacts:
              - artifact: test-artifact
                versions:
                  - version: "2025-01-01"
                    distributions:
                      - file: https://example.com/slow.nt.gz
                        status: pending
        """)

        with tempfile.TemporaryDirectory() as tmp:
            yaml_path = self._write_yaml(tmp, yaml_content)

            check_url_and_update_yaml(yaml_path)

            mock_notifier.notify.assert_called_once()
            call_args = mock_notifier.notify.call_args
            self.assertEqual(call_args[0][0], KG_UNAVAILABLE)
            self.assertEqual(call_args[0][1]["error"], "Request timed out")
            self.assertNotIn("status_code", call_args[0][1])

    @patch("check_url_update_yaml.requests.head")
    @patch("check_url_update_yaml.get_notifier")
    def test_no_duplicate_alert_when_status_remains_error(self, mock_get_notifier, mock_head):
        """If a URL was already error and remains error, no duplicate alert is sent."""
        mock_notifier = MagicMock()
        mock_get_notifier.return_value = mock_notifier

        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_head.return_value = mock_resp

        yaml_content = textwrap.dedent("""\
            artifacts:
              - artifact: test-artifact
                versions:
                  - version: "2025-01-01"
                    distributions:
                      - file: https://example.com/broken.nt.gz
                        status: error
        """)

        with tempfile.TemporaryDirectory() as tmp:
            yaml_path = self._write_yaml(tmp, yaml_content)

            check_url_and_update_yaml(yaml_path)

            mock_notifier.notify.assert_not_called()


# --------------------------------------------------
# Integration: Production run_daily_check
# --------------------------------------------------

class TestDailyCheckProductionIntegration(unittest.TestCase):
    """
    Test production run_daily_check function with temporary KG directories.
    """

    @patch("daily_check.subprocess.run")
    @patch("daily_check.get_notifier")
    def test_added_version_triggers_new_kg_version(self, mock_get_notifier, mock_subproc):
        """Detecting a new version during run_daily_check fires NEW_KG_VERSION."""
        mock_notifier = MagicMock()
        mock_get_notifier.return_value = mock_notifier

        initial_yaml = textwrap.dedent("""\
            check-new-release: check.py
            artifacts:
              - artifact: snapshot
                versions:
                  - version: "2025-10-01"
                    distributions:
                      - file: https://example.com/v1.nt.gz
        """)

        updated_yaml = textwrap.dedent("""\
            check-new-release: check.py
            artifacts:
              - artifact: snapshot
                versions:
                  - version: "2025-10-01"
                    distributions:
                      - file: https://example.com/v1.nt.gz
                  - version: "2025-11-01"
                    distributions:
                      - file: https://example.com/v2.nt.gz
        """)

        with tempfile.TemporaryDirectory() as tmp_root:
            kg_dir = os.path.join(tmp_root, "knowledge-graphs", "test-kg")
            os.makedirs(kg_dir)

            metadata_path = os.path.join(kg_dir, "metadata.yaml")
            script_path = os.path.join(kg_dir, "check.py")

            with open(metadata_path, "w") as f:
                f.write(initial_yaml)
            with open(script_path, "w") as f:
                f.write("# dummy script\n")

            # Simulate subprocess updating the metadata.yaml
            def side_effect(*args, **kwargs):
                with open(metadata_path, "w") as f:
                    f.write(updated_yaml)

            mock_subproc.side_effect = side_effect

            with patch("daily_check.KGS_ROOT", os.path.join(tmp_root, "knowledge-graphs")), \
                 patch("daily_check.notifier", mock_notifier):
                run_daily_check()

            mock_notifier.notify.assert_called_once()
            event, payload = mock_notifier.notify.call_args[0]
            self.assertEqual(event, NEW_KG_VERSION)
            self.assertEqual(payload["kg_name"], "test-kg")
            self.assertEqual(payload["old_version"], "2025-10-01")
            self.assertEqual(payload["new_version"], "2025-11-01")
            self.assertEqual(payload["release_url"], "https://example.com/v2.nt.gz")

    @patch("daily_check.subprocess.run")
    @patch("daily_check.get_notifier")
    def test_unchanged_metadata_produces_no_version_alert(self, mock_get_notifier, mock_subproc):
        """When check script produces no new version, no notification is sent."""
        mock_notifier = MagicMock()
        mock_get_notifier.return_value = mock_notifier

        initial_yaml = textwrap.dedent("""\
            check-new-release: check.py
            artifacts:
              - artifact: snapshot
                versions:
                  - version: "2025-10-01"
        """)

        with tempfile.TemporaryDirectory() as tmp_root:
            kg_dir = os.path.join(tmp_root, "knowledge-graphs", "test-kg")
            os.makedirs(kg_dir)

            metadata_path = os.path.join(kg_dir, "metadata.yaml")
            script_path = os.path.join(kg_dir, "check.py")

            with open(metadata_path, "w") as f:
                f.write(initial_yaml)
            with open(script_path, "w") as f:
                f.write("# dummy script\n")

            with patch("daily_check.KGS_ROOT", os.path.join(tmp_root, "knowledge-graphs")), \
                 patch("daily_check.notifier", mock_notifier):
                run_daily_check()

            mock_notifier.notify.assert_not_called()


if __name__ == "__main__":
    unittest.main()
