# coding=utf-8
import unittest
from unittest.mock import MagicMock, patch
import requests

from octoprint_prusalink_bridge import PrusaLinkClient, PrusaLinkBridgePlugin


class TestPrusaLinkClient(unittest.TestCase):
    def setUp(self):
        self.client = PrusaLinkClient()

    @patch("requests.get")
    def test_get_status_success(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "printer": {
                "state": "PRINTING",
                "temp_nozzle": 215.4,
                "target_nozzle": 215.0,
                "temp_bed": 60.1,
                "target_bed": 60.0,
            },
            "job": {
                "id": 42,
                "progress": 35.5,
                "time_printing": 300,
                "time_remaining": 600,
            },
        }
        mock_get.return_value = mock_resp

        success, data, err = self.client.get_status("192.168.1.100", "secret_key")
        self.assertTrue(success)
        self.assertEqual(data["printer"]["state"], "PRINTING")
        self.assertEqual(data["printer"]["temp_nozzle"], 215.4)
        mock_get.assert_called_once_with(
            "http://192.168.1.100/api/v1/status",
            headers={"Accept": "application/json", "User-Agent": "OctoPrint-PrusaLink-Bridge/0.1.0", "X-Api-Key": "secret_key"},
            timeout=3.0,
        )

    @patch("requests.get")
    def test_get_status_unauthorized(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_get.return_value = mock_resp

        success, data, err = self.client.get_status("192.168.1.100", "wrong_key")
        self.assertFalse(success)
        self.assertIn("401 Unauthorized", err)

    @patch("requests.get")
    def test_get_status_timeout(self, mock_get):
        mock_get.side_effect = requests.exceptions.Timeout()
        success, data, err = self.client.get_status("192.168.1.100", "key")
        self.assertFalse(success)
        self.assertIn("timeout", err.lower())

    @patch("requests.get")
    def test_get_job_no_content(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 204  # No job running
        mock_get.return_value = mock_resp

        success, data, err = self.client.get_job("192.168.1.100", "key")
        self.assertTrue(success)
        self.assertIsNone(data)

    @patch("requests.post")
    def test_send_job_command_primary_success(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_post.return_value = mock_resp

        success, msg = self.client.send_job_command("192.168.1.100", "key", "pause")
        self.assertTrue(success)
        mock_post.assert_called_once_with(
            "http://192.168.1.100/api/v1/job",
            json={"command": "pause"},
            headers={
                "Accept": "application/json",
                "User-Agent": "OctoPrint-PrusaLink-Bridge/0.1.0",
                "X-Api-Key": "key",
                "Content-Type": "application/json",
            },
            timeout=5.0,
        )

    @patch("requests.delete")
    @patch("requests.post")
    def test_send_job_command_fallback_cancel(self, mock_post, mock_delete):
        # Primary POST /api/v1/job returns 405 (Method Not Allowed)
        post_resp = MagicMock()
        post_resp.status_code = 405
        mock_post.return_value = post_resp

        # Fallback DELETE /api/v1/job/42 succeeds
        del_resp = MagicMock()
        del_resp.status_code = 204
        mock_delete.return_value = del_resp

        success, msg = self.client.send_job_command("192.168.1.100", "key", "cancel", job_id=42)
        self.assertTrue(success)
        self.assertIn("stopped job 42", msg)
        mock_delete.assert_called_once()


class DummySettings:
    def __init__(self, data=None):
        self._data = data or {}

    def get(self, path):
        curr = self._data
        for p in path:
            if isinstance(curr, dict) and p in curr:
                curr = curr[p]
            else:
                return None
        return curr

    def get_boolean(self, path):
        val = self.get(path)
        return bool(val)

    def set(self, path, val):
        if not path:
            self._data = val
        else:
            self._data[path[0]] = val


class DummyPrinter:
    def __init__(self):
        self._printing = False
        self._paused = False
        self._operational = False
        self._state_str = "Offline"
        self._state_id = "OFFLINE"
        self._temps = []
        self._stateMonitor = MagicMock()
        self._dict = dict

    def is_printing(self, *args, **kwargs):
        return self._printing

    def is_paused(self, *args, **kwargs):
        return self._paused

    def is_operational(self, *args, **kwargs):
        return self._operational

    def get_state_string(self, *args, **kwargs):
        return self._state_str

    def get_state_id(self, *args, **kwargs):
        return self._state_id

    def pause_print(self, user=None, *args, **kwargs):
        self._paused = True

    def cancel_print(self, user=None, *args, **kwargs):
        self._printing = False
        self._paused = False

    def resume_print(self, user=None, *args, **kwargs):
        self._paused = False
        self._printing = True

    def get_current_data(self, *args, **kwargs):
        return {
            "state": {"text": self._state_str, "flags": {"printing": self._printing, "paused": self._paused}},
            "job": {"file": {"name": None}},
            "progress": {"completion": None, "printTime": None, "printTimeLeft": None},
        }

    def get_current_temperatures(self, *args, **kwargs):
        return {}


class TestPrusaLinkBridgePlugin(unittest.TestCase):
    def setUp(self):
        self.plugin = PrusaLinkBridgePlugin()
        self.plugin._settings = DummySettings({
            "prusa_ip": "192.168.1.120",
            "prusa_api_key": "test_api_key",
            "poll_interval": 2.0,
            "sync_temperatures": True,
        })
        self.plugin._printer = DummyPrinter()
        self.plugin._event_bus = MagicMock()
        self.plugin._wrap_printer_methods()

    def tearDown(self):
        self.plugin._unwrap_printer_methods()

    def test_settings_defaults(self):
        defaults = self.plugin.get_settings_defaults()
        self.assertEqual(defaults["poll_interval"], 2.0)
        self.assertTrue(defaults["sync_temperatures"])
        self.assertEqual(defaults["prusa_ip"], "")
        self.assertEqual(defaults["prusa_api_key"], "")

    def test_printing_mirroring_and_obico_compatibility(self):
        # 1. Simulate PrusaLink reporting PRINTING
        status_data = {
            "printer": {
                "state": "PRINTING",
                "temp_nozzle": 215.0,
                "target_nozzle": 215.0,
                "temp_bed": 60.0,
                "target_bed": 60.0,
            },
            "job": {
                "id": 101,
                "progress": 45.2,
                "time_printing": 540,
                "time_remaining": 660,
                "file": {
                    "name": "benchy.gcode",
                    "display_name": "3DBenchy_PLA.gcode",
                    "size": 123456,
                },
            },
        }

        # Mirror status
        with patch.object(self.plugin._client, "get_status", return_value=(True, status_data, "")), \
             patch.object(self.plugin._client, "get_job", return_value=(True, status_data["job"], "")):
            self.plugin._poll_prusalink("192.168.1.120", "test_api_key")

        # Verify that OctoPrint's printer interface reports is_printing() == True
        self.assertTrue(self.plugin._printer.is_printing())
        self.assertFalse(self.plugin._printer.is_paused())
        self.assertTrue(self.plugin._printer.is_operational())
        self.assertEqual(self.plugin._printer.get_state_string(), "Printing")
        self.assertEqual(self.plugin._printer.get_state_id(), "PRINTING")

        # Verify get_current_data includes mirrored job and progress
        current_data = self.plugin._printer.get_current_data()
        self.assertTrue(current_data["state"]["flags"]["printing"])
        self.assertEqual(current_data["progress"]["completion"], 45.2)
        self.assertEqual(current_data["job"]["file"]["name"], "3DBenchy_PLA.gcode")

        # Verify temperatures were fed to _temps
        self.assertTrue(len(self.plugin._printer._temps) > 0)
        last_temp = self.plugin._printer._temps[-1]
        self.assertEqual(last_temp["tool0"]["actual"], 215.0)
        self.assertEqual(last_temp["bed"]["actual"], 60.0)

        # 2. Test Obico pausing print via self._printer.pause_print()
        with patch.object(self.plugin, "send_prusalink_command") as mock_send_cmd:
            self.plugin._printer.pause_print()
            mock_send_cmd.assert_called_once_with("pause")

        # 3. Test Obico cancelling print via self._printer.cancel_print()
        with patch.object(self.plugin, "send_prusalink_command") as mock_send_cmd:
            self.plugin._printer.cancel_print()
            mock_send_cmd.assert_called_once_with("cancel")

    def test_action_command_hook(self):
        with patch.object(self.plugin, "send_prusalink_command") as mock_send_cmd:
            res = self.plugin.hook_action_command(None, "// action:cancel", "cancel")
            self.assertEqual(res, ("cancel",))
            mock_send_cmd.assert_called_once_with("cancel")

    def test_finished_transition(self):
        # First set printing state
        self.plugin._is_prusalink_printing = True
        self.plugin._current_job_id = 99
        self.plugin._current_job_file = "cube.gcode"

        status_finished = {
            "printer": {"state": "FINISHED", "temp_nozzle": 30.0, "temp_bed": 25.0},
            "job": {"id": 99, "progress": 100.0, "time_printing": 1200, "time_remaining": 0},
        }

        with patch.object(self.plugin._client, "get_status", return_value=(True, status_finished, "")), \
             patch.object(self.plugin._client, "get_job", return_value=(True, status_finished["job"], "")):
            self.plugin._poll_prusalink("192.168.1.120", "test_api_key")

        self.assertFalse(self.plugin._printer.is_printing())
        self.assertFalse(self.plugin._is_prusalink_printing)

    def test_paused_state_mirroring(self):
        status_paused = {
            "printer": {"state": "PAUSED", "temp_nozzle": 200.0, "temp_bed": 60.0},
            "job": {"id": 102, "progress": 50.0, "time_printing": 600, "time_remaining": 600},
        }
        with patch.object(self.plugin._client, "get_status", return_value=(True, status_paused, "")), \
             patch.object(self.plugin._client, "get_job", return_value=(True, status_paused["job"], "")):
            self.plugin._poll_prusalink("192.168.1.120", "test_api_key")

        self.assertTrue(self.plugin._printer.is_paused())
        self.assertFalse(self.plugin._printer.is_printing())
        self.assertEqual(self.plugin._printer.get_state_string(), "Paused")
        self.assertEqual(self.plugin._printer.get_state_id(), "PAUSED")

    def test_resume_wrapper(self):
        self.plugin._is_prusalink_paused = True
        with patch.object(self.plugin, "send_prusalink_command") as mock_send_cmd:
            self.plugin._printer.resume_print()
            mock_send_cmd.assert_called_once_with("resume")

    def test_temperature_injection_when_offline(self):
        # When serial comm is offline, get_current_temperatures should return injected PrusaLink temps
        self.plugin._current_temps = {
            "tool0": {"actual": 215.0, "target": 215.0, "offset": 0},
            "bed": {"actual": 60.0, "target": 60.0, "offset": 0},
        }
        temps = self.plugin._printer.get_current_temperatures()
        self.assertEqual(temps["tool0"]["actual"], 215.0)
        self.assertEqual(temps["bed"]["actual"], 60.0)

    def test_send_command_missing_ip(self):
        self.plugin._settings.set(["prusa_ip"], "")
        success, msg = self.plugin.send_prusalink_command("pause")
        self.assertFalse(success)
        self.assertIn("IP not configured", msg)

    def test_log_spam_prevention(self):
        with patch.object(self.plugin._client, "get_status", return_value=(False, None, "Connection refused")), \
             patch.object(self.plugin._logger, "warning") as mock_warn, \
             patch.object(self.plugin._logger, "debug") as mock_debug:

            # First failure: should log a warning
            self.plugin._poll_prusalink("192.168.1.120", "test_api_key")
            self.assertEqual(mock_warn.call_count, 1)

            # Second failure: should NOT log another warning (prevents spam)
            self.plugin._poll_prusalink("192.168.1.120", "test_api_key")
            self.assertEqual(mock_warn.call_count, 1)

    def test_additional_state_data_hook(self):
        self.plugin._is_prusalink_printing = True
        self.plugin._current_job_id = 42
        data = self.plugin.hook_additional_state_data()
        self.assertIn("prusalink_bridge", data)
        self.assertTrue(data["prusalink_bridge"]["printing"])
        self.assertEqual(data["prusalink_bridge"]["job_id"], 42)


if __name__ == "__main__":
    unittest.main()
