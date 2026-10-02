# coding=utf-8
from __future__ import absolute_import

import logging
import re
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

import requests

try:
    import octoprint.plugin
    from octoprint.events import Events
except ImportError:
    # Fallback to allow importing outside of full OctoPrint environment (e.g. unit tests)
    octoprint = None
    Events = None

__version__ = "0.2.0"


class PrusaLinkClient:
    """
    HTTP REST client for communicating with PrusaLink API on Prusa MK3.5/MK4/XL/CORE One printers.
    """

    def __init__(self, logger: Optional[logging.Logger] = None):
        self._logger = logger or logging.getLogger(__name__)

    @staticmethod
    def _build_headers(api_key: str) -> Dict[str, str]:
        headers = {
            "Accept": "application/json",
            "User-Agent": f"OctoPrint-PrusaLink-Bridge/{__version__}",
        }
        if api_key:
            headers["X-Api-Key"] = api_key
        return headers

    def get_status(self, ip: str, api_key: str, timeout: float = 3.0) -> Tuple[bool, Optional[Dict[str, Any]], str]:
        """
        Calls GET http://<ip>/api/v1/status.
        Returns: (success, data_dict, error_message)
        """
        url = f"http://{ip}/api/v1/status"
        headers = self._build_headers(api_key)
        try:
            resp = requests.get(url, headers=headers, timeout=timeout)
            if resp.status_code == 200:
                return True, resp.json(), ""
            elif resp.status_code == 401:
                return False, None, "401 Unauthorized: Invalid PrusaLink API Key"
            elif resp.status_code == 404:
                return False, None, "404 Not Found: /api/v1/status endpoint not found"
            else:
                return False, None, f"HTTP {resp.status_code}: {resp.text.strip()}"
        except requests.exceptions.Timeout:
            return False, None, f"Connection timeout after {timeout}s"
        except requests.exceptions.ConnectionError as e:
            return False, None, f"Connection error: {e}"
        except Exception as e:
            return False, None, f"Unexpected error: {e}"

    def get_job(self, ip: str, api_key: str, timeout: float = 3.0) -> Tuple[bool, Optional[Dict[str, Any]], str]:
        """
        Calls GET http://<ip>/api/v1/job.
        Returns: (success, data_dict, error_message).
        Note: 204 No Content means printer is operational but no job is currently running.
        """
        url = f"http://{ip}/api/v1/job"
        headers = self._build_headers(api_key)
        try:
            resp = requests.get(url, headers=headers, timeout=timeout)
            if resp.status_code == 200:
                try:
                    return True, resp.json(), ""
                except ValueError:
                    return True, None, ""
            elif resp.status_code == 204:
                # No active print job
                return True, None, ""
            elif resp.status_code == 401:
                return False, None, "401 Unauthorized: Invalid PrusaLink API Key"
            else:
                return False, None, f"HTTP {resp.status_code}: {resp.text.strip()}"
        except requests.exceptions.Timeout:
            return False, None, f"Connection timeout after {timeout}s"
        except requests.exceptions.ConnectionError as e:
            return False, None, f"Connection error: {e}"
        except Exception as e:
            return False, None, f"Unexpected error: {e}"

    def get_info(self, ip: str, api_key: str, timeout: float = 3.0) -> Tuple[bool, Optional[Dict[str, Any]], str]:
        """
        Calls GET http://<ip>/api/v1/info to retrieve printer metadata.
        """
        url = f"http://{ip}/api/v1/info"
        headers = self._build_headers(api_key)
        try:
            resp = requests.get(url, headers=headers, timeout=timeout)
            if resp.status_code == 200:
                return True, resp.json(), ""
            return False, None, f"HTTP {resp.status_code}"
        except Exception as e:
            return False, None, str(e)

    def send_job_command(
        self,
        ip: str,
        api_key: str,
        command: str,
        job_id: Optional[int] = None,
        timeout: float = 5.0,
    ) -> Tuple[bool, str]:
        """
        Sends job control command ('pause', 'cancel', 'resume').
        First attempts standard requested endpoint:
          POST http://<ip>/api/v1/job with {"command": <command>}
        If not supported (e.g. 404/405) and job_id is known, falls back to PrusaLink native REST endpoints:
          - Cancel: DELETE http://<ip>/api/v1/job/<job_id>
          - Pause:  PUT http://<ip>/api/v1/job/<job_id>/pause
          - Resume: PUT http://<ip>/api/v1/job/<job_id>/resume
        """
        cmd_lower = command.lower()
        headers = self._build_headers(api_key)
        headers["Content-Type"] = "application/json"

        # 1. Primary method: POST /api/v1/job with {"command": ...}
        primary_url = f"http://{ip}/api/v1/job"
        payload = {"command": cmd_lower}

        try:
            resp = requests.post(primary_url, json=payload, headers=headers, timeout=timeout)
            if resp.status_code in (200, 204):
                return True, f"PrusaLink accepted command '{cmd_lower}' (HTTP {resp.status_code})"
            elif resp.status_code not in (404, 405):
                return False, f"PrusaLink returned HTTP {resp.status_code}: {resp.text.strip()}"
        except Exception as e:
            self._logger.warning(f"Error calling POST {primary_url}: {e}")

        # 2. Fallback to native REST endpoints if job_id is known or can be addressed
        if job_id is not None:
            try:
                if cmd_lower in ("cancel", "stop"):
                    fb_url = f"http://{ip}/api/v1/job/{job_id}"
                    resp = requests.delete(fb_url, headers=headers, timeout=timeout)
                    if resp.status_code in (200, 204):
                        return True, f"PrusaLink stopped job {job_id} via DELETE (HTTP {resp.status_code})"
                    return False, f"DELETE {fb_url} returned HTTP {resp.status_code}: {resp.text.strip()}"

                elif cmd_lower == "pause":
                    fb_url = f"http://{ip}/api/v1/job/{job_id}/pause"
                    resp = requests.put(fb_url, headers=headers, timeout=timeout)
                    if resp.status_code in (200, 204):
                        return True, f"PrusaLink paused job {job_id} via PUT (HTTP {resp.status_code})"
                    return False, f"PUT {fb_url} returned HTTP {resp.status_code}: {resp.text.strip()}"

                elif cmd_lower in ("resume", "continue"):
                    fb_url = f"http://{ip}/api/v1/job/{job_id}/resume"
                    resp = requests.put(fb_url, headers=headers, timeout=timeout)
                    if resp.status_code in (200, 204):
                        return True, f"PrusaLink resumed job {job_id} via PUT (HTTP {resp.status_code})"
                    return False, f"PUT {fb_url} returned HTTP {resp.status_code}: {resp.text.strip()}"
            except Exception as e:
                return False, f"Fallback command execution failed: {e}"

        return False, f"Failed to execute '{cmd_lower}' on PrusaLink"

    def get_files_list(self, ip: str, api_key: str, timeout: float = 4.0) -> Tuple[bool, List[Dict[str, Any]], str]:
        """
        Retrieves list of files on the printer storage (e.g. USB) from /api/v1/files/usb.
        """
        url = f"http://{ip}/api/v1/files/usb"
        headers = self._build_headers(api_key)
        try:
            resp = requests.get(url, headers=headers, timeout=timeout)
            if resp.status_code == 200:
                data = resp.json()
                children = data.get("children", []) if isinstance(data, dict) else []
                return True, children, ""
            return False, [], f"HTTP {resp.status_code}"
        except Exception as e:
            return False, [], str(e)

    def get_thumbnail(self, ip: str, api_key: str, thumb_path: str, timeout: float = 5.0) -> Optional[bytes]:
        """
        Fetches thumbnail image binary data from PrusaLink (e.g. /thumb/l/usb/MUG-CU~4.BGC).
        """
        if not thumb_path:
            return None
        clean_path = thumb_path if thumb_path.startswith("/") else ("/" + thumb_path)
        url = f"http://{ip}{clean_path}"
        headers = self._build_headers(api_key)
        try:
            resp = requests.get(url, headers=headers, timeout=timeout)
            if resp.status_code == 200 and resp.content and resp.content.startswith(b"\x89PNG"):
                return resp.content
            return None
        except Exception as e:
            self._logger.debug(f"Error fetching thumbnail from {url}: {e}")
            return None

    def get_file_header(self, ip: str, api_key: str, file_path: str, max_bytes: int = 32768, timeout: float = 4.0) -> bytes:
        """
        Streams first max_bytes of a file from PrusaLink (e.g. /usb/MINIBO~2.BGC) to inspect metadata.
        """
        clean_path = file_path if file_path.startswith("/") else ("/" + file_path)
        url = f"http://{ip}{clean_path}"
        headers = self._build_headers(api_key)
        chunk = b""
        try:
            with requests.get(url, headers=headers, stream=True, timeout=timeout) as resp:
                if resp.status_code == 200:
                    for c in resp.iter_content(chunk_size=4096):
                        chunk += c
                        if len(chunk) >= max_bytes:
                            break
        except Exception as e:
            self._logger.debug(f"Error streaming file header from {url}: {e}")
        return chunk


if octoprint:
    _PluginBases = (
        octoprint.plugin.StartupPlugin,
        octoprint.plugin.ShutdownPlugin,
        octoprint.plugin.SettingsPlugin,
        octoprint.plugin.TemplatePlugin,
        octoprint.plugin.AssetPlugin,
        octoprint.plugin.SimpleApiPlugin,
        octoprint.plugin.EventHandlerPlugin,
        octoprint.plugin.OctoPrintPlugin,
    )
else:
    class DummyStartupPlugin:
        pass

    class DummyShutdownPlugin:
        pass

    class DummySettingsPlugin:
        def on_settings_save(self, data):
            pass

    class DummyTemplatePlugin:
        pass

    class DummyAssetPlugin:
        pass

    class DummySimpleApiPlugin:
        pass

    class DummyEventHandlerPlugin:
        pass

    class DummyOctoPrintPlugin:
        pass

    _PluginBases = (
        DummyStartupPlugin,
        DummyShutdownPlugin,
        DummySettingsPlugin,
        DummyTemplatePlugin,
        DummyAssetPlugin,
        DummySimpleApiPlugin,
        DummyEventHandlerPlugin,
        DummyOctoPrintPlugin,
    )


class PrusaLinkBridgePlugin(*_PluginBases):
    def __init__(self):
        self._logger = logging.getLogger("octoprint.plugins.prusalink_bridge")
        self._client = PrusaLinkClient(self._logger)

        # Worker thread control
        self._worker_thread = None
        self._stop_event = threading.Event()

        # Connection and telemetry state
        self._prusalink_online = False
        self._connection_logged = None  # None: initial, True: logged online, False: logged offline
        self._prusalink_state = "OFFLINE"
        self._previous_state = None

        # Print and job tracking
        self._is_prusalink_printing = False
        self._is_prusalink_paused = False
        self._current_job_id = None
        self._current_job_file = None
        self._current_progress = None
        self._current_time_printing = None
        self._current_time_remaining = None
        self._last_fired_progress = -1

        # Temperature tracking
        self._current_temps = {}

        # Z axis tracking
        self._current_axis_z = None

        # Thumbnail and filament caching
        self._files_cache = {}
        self._last_files_poll_time = 0
        self._thumbnail_cache = {}  # {path: (bytes, timestamp)}
        self._current_thumbnail_path = None
        self._current_filament = {
            "type": None,
            "weight_g": None,
            "length_m": None,
            "volume_cm3": None,
            "cost": None,
        }

        self._first_layer_inspecting = False

        # Telemetry data dictionary for UI & API
        self._prusalink_info = {
            "online": False,
            "state": "OFFLINE",
            "temp_nozzle": None,
            "target_nozzle": None,
            "temp_bed": None,
            "target_bed": None,
            "axis_x": None,
            "axis_y": None,
            "axis_z": None,
            "flow": None,
            "speed": None,
            "fan_hotend": None,
            "fan_print": None,
            "job_file": None,
            "progress": None,
            "time_printing": None,
            "time_remaining": None,
            "prusa_ip": None,
            "printer_name": "Prusa 3D Drucker",
            "thumbnail_url": None,
            "thumbnail_path": None,
            "filament_type": None,
            "filament_weight_g": None,
            "filament_length_m": None,
            "filament_volume_cm3": None,
            "filament_cost": None,
            "first_layer_inspecting": False,
        }
        self._prusa_model_name = "Prusa 3D Drucker"

        # Saved original printer methods for clean unwrap
        self._orig_printer_methods = {}

    # ~~ SettingsPlugin mixin

    def get_settings_defaults(self):
        return {
            "prusa_ip": "",
            "prusa_api_key": "",
            "poll_interval": 2.0,
            "sync_temperatures": True,
            "sync_obico_nozzlecam": True,
        }

    def on_settings_save(self, data):
        if octoprint:
            octoprint.plugin.SettingsPlugin.on_settings_save(self, data)
        else:
            if hasattr(self, "_settings") and self._settings:
                self._settings.set([], data)

        self._logger.info("Settings updated, waking worker thread for immediate poll")
        # Wake up worker thread so new settings (e.g. IP, interval) take effect immediately
        self._stop_event.set()
        # Create fresh stop event for continued polling
        self._stop_event = threading.Event()

    # ~~ TemplatePlugin mixin

    def get_template_configs(self):
        return [
            {
                "type": "settings",
                "name": "PrusaLink Bridge",
                "template": "prusalink_bridge_settings.jinja2",
                "custom_bindings": True,
            },
            {
                "type": "tab",
                "name": "PrusaLink",
                "template": "prusalink_bridge_tab.jinja2",
                "custom_bindings": True,
            },
            {
                "type": "sidebar",
                "name": "PrusaLink",
                "template": "prusalink_bridge_sidebar.jinja2",
                "custom_bindings": True,
            },
        ]

    # ~~ AssetPlugin mixin

    def get_assets(self):
        return {
            "js": ["js/prusalink_bridge.js"],
            "css": ["css/prusalink_bridge.css"],
        }

    # ~~ SimpleApiPlugin mixin

    def get_api_commands(self):
        return {
            "test_connection": ["prusa_ip", "prusa_api_key"],
            "send_command": ["command"],
        }

    def on_api_command(self, command, data):
        import flask

        if command == "test_connection":
            ip = data.get("prusa_ip") or (self._settings.get(["prusa_ip"]) if hasattr(self, "_settings") else "")
            key = data.get("prusa_api_key") or (self._settings.get(["prusa_api_key"]) if hasattr(self, "_settings") else "")

            if not ip:
                return flask.jsonify({"success": False, "message": "Bitte gib eine IP-Adresse an."})

            # Test /api/v1/status
            success, status_data, err = self._client.get_status(ip, key, timeout=4.0)
            if not success:
                return flask.jsonify({"success": False, "message": f"Verbindungsfehler: {err}"})

            # Also try /api/v1/info for model name
            _, info_data, _ = self._client.get_info(ip, key, timeout=2.0)
            printer_name = "Prusa 3D Drucker"
            if info_data and "name" in info_data:
                printer_name = info_data.get("name")

            state_text = "Unbekannt"
            if status_data:
                state_text = status_data.get("printer", {}).get("state", "Online")

            return flask.jsonify({
                "success": True,
                "message": f"Erfolgreich verbunden mit {printer_name}! Status: {state_text}",
                "state": state_text,
                "printer_name": printer_name,
            })

        elif command == "send_command":
            cmd = data.get("command", "")
            success, msg = self.send_prusalink_command(cmd)
            return flask.jsonify({"success": success, "message": msg})

        return flask.jsonify({"error": "Unbekannter Befehl"}), 400

    def on_api_get(self, request):
        import flask
        # Serve thumbnail image
        if request.args.get("thumbnail"):
            req_path = request.args.get("path") or self._current_thumbnail_path or self._prusalink_info.get("thumbnail_path")
            if not req_path:
                return flask.abort(404)
            now = time.time()
            if req_path in self._thumbnail_cache:
                cached_data, cached_time = self._thumbnail_cache[req_path]
                if now - cached_time < 3600:
                    resp = flask.Response(cached_data, mimetype="image/png")
                    resp.headers["Cache-Control"] = "public, max-age=3600"
                    return resp

            prusa_ip = (self._settings.get(["prusa_ip"]) if hasattr(self, "_settings") else "") or ""
            prusa_api_key = (self._settings.get(["prusa_api_key"]) if hasattr(self, "_settings") else "") or ""
            if not prusa_ip:
                return flask.abort(404)

            img_bytes = self._client.get_thumbnail(prusa_ip.strip(), prusa_api_key.strip(), req_path)
            if not img_bytes:
                return flask.abort(404)

            self._thumbnail_cache[req_path] = (img_bytes, now)
            resp = flask.Response(img_bytes, mimetype="image/png")
            resp.headers["Cache-Control"] = "public, max-age=3600"
            return resp

        info = dict(getattr(self, "_prusalink_info", {}))
        return flask.jsonify(info)

    def is_api_protected(self):
        return False

    # ~~ StartupPlugin & ShutdownPlugin mixins

    def on_after_startup(self):
        self._logger.info("OctoPrint-PrusaLink-Bridge starting up...")
        self._wrap_printer_methods()
        self._start_worker_thread()

    def on_shutdown(self):
        self._logger.info("OctoPrint-PrusaLink-Bridge shutting down...")
        self._stop_worker_thread()
        self._unwrap_printer_methods()

    # ~~ Background Worker Thread

    def _start_worker_thread(self):
        if self._worker_thread is not None and self._worker_thread.is_alive():
            return
        self._stop_event.clear()
        self._worker_thread = threading.Thread(
            target=self._worker_loop,
            name="PrusaLinkBridgeWorker",
            daemon=True,
        )
        self._worker_thread.start()
        self._logger.info("PrusaLink background polling thread started")

    def _stop_worker_thread(self):
        self._stop_event.set()
        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=3.0)
        self._logger.info("PrusaLink background polling thread stopped")

    def _worker_loop(self):
        while not self._stop_event.is_set():
            try:
                poll_interval = 2.0
                if hasattr(self, "_settings") and self._settings:
                    prusa_ip = (self._settings.get(["prusa_ip"]) or "").strip()
                    prusa_api_key = (self._settings.get(["prusa_api_key"]) or "").strip()
                    try:
                        poll_interval = float(self._settings.get(["poll_interval"]) or 2.0)
                        poll_interval = max(0.5, min(poll_interval, 60.0))
                    except (ValueError, TypeError):
                        poll_interval = 2.0
                else:
                    prusa_ip = ""
                    prusa_api_key = ""

                if not prusa_ip:
                    # PrusaLink IP not configured yet, wait quietly
                    if self._connection_logged is not False:
                        self._logger.debug("PrusaLink IP not configured, waiting...")
                    self._stop_event.wait(timeout=3.0)
                    continue

                # Query status and job
                self._poll_prusalink(prusa_ip, prusa_api_key)

            except Exception as e:
                self._logger.exception(f"Unexpected error in PrusaLink worker loop: {e}")

            # Wait for poll_interval or immediate wake-up
            self._stop_event.wait(timeout=poll_interval)

    def _poll_prusalink(self, ip: str, api_key: str):
        # 1. GET /api/v1/status
        status_ok, status_data, status_err = self._client.get_status(ip, api_key, timeout=3.5)

        if not status_ok:
            if self._connection_logged is not False:
                self._logger.warning(f"Connection to PrusaLink at {ip} lost/unavailable: {status_err}")
                self._connection_logged = False
            self._handle_disconnected()
            return

        # Connected successfully
        if self._connection_logged is not True:
            self._logger.info(f"Connected to PrusaLink at {ip} successfully")
            self._connection_logged = True
        self._prusalink_online = True

        # Extract telemetry & status
        printer_data = status_data.get("printer", {}) if status_data else {}
        telemetry_fallback = status_data.get("telemetry", {}) if status_data else {}

        raw_state = printer_data.get("state") or telemetry_fallback.get("state") or "OPERATIONAL"
        state_str = str(raw_state).upper()
        self._prusalink_state = state_str

        # Temperatures
        nozzle_actual = printer_data.get("temp_nozzle")
        if nozzle_actual is None:
            nozzle_actual = telemetry_fallback.get("temp-nozzle")

        nozzle_target = printer_data.get("target_nozzle")
        if nozzle_target is None:
            nozzle_target = telemetry_fallback.get("target-nozzle", 0.0)

        bed_actual = printer_data.get("temp_bed")
        if bed_actual is None:
            bed_actual = telemetry_fallback.get("temp-bed")

        bed_target = printer_data.get("target_bed")
        if bed_target is None:
            bed_target = telemetry_fallback.get("target-bed", 0.0)

        axis_z = printer_data.get("axis_z")
        if axis_z is None:
            axis_z = telemetry_fallback.get("axis-z")

        axis_x = printer_data.get("axis_x")
        if axis_x is None:
            axis_x = telemetry_fallback.get("axis-x")

        axis_y = printer_data.get("axis_y")
        if axis_y is None:
            axis_y = telemetry_fallback.get("axis-y")

        flow = printer_data.get("flow")
        speed = printer_data.get("speed")
        fan_hotend = printer_data.get("fan_hotend")
        fan_print = printer_data.get("fan_print")

        telemetry_dict = {
            "temp_nozzle": nozzle_actual,
            "target_nozzle": nozzle_target,
            "temp_bed": bed_actual,
            "target_bed": bed_target,
            "axis_x": axis_x,
            "axis_y": axis_y,
            "axis_z": axis_z,
            "flow": flow,
            "speed": speed,
            "fan_hotend": fan_hotend,
            "fan_print": fan_print,
        }
        if axis_z is not None:
            try:
                telemetry_dict["axis_z"] = float(axis_z)
            except (ValueError, TypeError):
                pass

        # 2. GET /api/v1/job for detailed print job information
        job_data = {}
        if state_str in ("PRINTING", "PAUSED", "FINISHED", "STOPPED", "BUSY"):
            job_ok, job_resp, job_err = self._client.get_job(ip, api_key, timeout=3.5)
            if job_ok and isinstance(job_resp, dict):
                job_data = job_resp
            else:
                # Fallback to status["job"] if available
                job_in_status = status_data.get("job") if status_data else None
                if isinstance(job_in_status, dict):
                    job_data = job_in_status

        # Retrieve model name once
        if getattr(self, "_prusa_model_name", None) in (None, "Prusa 3D Drucker"):
            info_ok, info_resp, _ = self._client.get_info(ip, api_key, timeout=2.0)
            if info_ok and isinstance(info_resp, dict):
                self._prusa_model_name = info_resp.get("name") or info_resp.get("hostname") or "Prusa MK3.5S"

        # Determine current or target file name
        target_filename = None
        if isinstance(job_data, dict) and "file" in job_data:
            f_info = job_data.get("file", {})
            if isinstance(f_info, dict):
                target_filename = f_info.get("display_name") or f_info.get("name")
        if not target_filename:
            target_filename = self._current_job_file

        self._update_file_metadata(ip, api_key, target_filename, job_data, state_str)

        # Synchronize into OctoPrint
        self._sync_to_octoprint(state_str, job_data, telemetry_dict)

        # Update telemetry data dictionary for UI and API
        is_printing = (state_str == "PRINTING")
        is_paused = (state_str == "PAUSED")
        thumb_url = f"/api/plugin/prusalink_bridge?thumbnail=1&t={self._current_job_id or int(time.time())}" if self._current_thumbnail_path else None
        self._prusalink_info = {
            "online": True,
            "state": state_str,
            "temp_nozzle": nozzle_actual,
            "target_nozzle": nozzle_target,
            "temp_bed": bed_actual,
            "target_bed": bed_target,
            "axis_x": axis_x,
            "axis_y": axis_y,
            "axis_z": self._current_axis_z,
            "flow": flow,
            "speed": speed,
            "fan_hotend": fan_hotend,
            "fan_print": fan_print,
            "job_file": self._current_job_file,
            "progress": self._current_progress if (is_printing or is_paused) else None,
            "time_printing": self._current_time_printing if (is_printing or is_paused) else None,
            "time_remaining": self._current_time_remaining if (is_printing or is_paused) else None,
            "prusa_ip": ip,
            "printer_name": getattr(self, "_prusa_model_name", "Prusa 3D Drucker"),
            "thumbnail_url": thumb_url,
            "thumbnail_path": self._current_thumbnail_path,
            "filament_type": self._current_filament.get("type"),
            "filament_weight_g": self._current_filament.get("weight_g"),
            "filament_length_m": self._current_filament.get("length_m"),
            "filament_volume_cm3": self._current_filament.get("volume_cm3"),
            "filament_cost": self._current_filament.get("cost"),
            "first_layer_inspecting": self._first_layer_inspecting,
        }
        if hasattr(self, "_plugin_manager") and self._plugin_manager is not None:
            try:
                self._plugin_manager.send_plugin_message(self._identifier, self._prusalink_info)
            except Exception as e:
                self._logger.debug(f"Error sending plugin message: {e}")

    def _update_file_metadata(self, ip: str, api_key: str, filename: Optional[str], job_data: Dict[str, Any], state_str: str = ""):
        """
        Updates thumbnail path and filament usage for the active or finished job file.
        """
        now = time.time()
        # Refresh files list cache if empty or every 60s
        if not self._files_cache or (now - self._last_files_poll_time > 60):
            ok, children, _ = self._client.get_files_list(ip, api_key)
            if ok:
                new_cache = {}
                for c in children:
                    name_83 = c.get("name")
                    disp_name = c.get("display_name") or name_83
                    entry = {
                        "name": name_83,
                        "display_name": disp_name,
                        "thumbnail": c.get("refs", {}).get("thumbnail") or f"/thumb/l/usb/{name_83}",
                        "download": c.get("refs", {}).get("download") or f"/usb/{name_83}",
                        "size": c.get("size"),
                        "m_timestamp": c.get("m_timestamp") or 0,
                    }
                    if name_83:
                        new_cache[name_83.lower()] = entry
                    if disp_name:
                        new_cache[disp_name.lower()] = entry
                self._files_cache = new_cache
                self._last_files_poll_time = now

        if not filename and state_str in ("FINISHED", "IDLE", "READY", "STOPPED"):
            if self._files_cache:
                latest_entry = max(self._files_cache.values(), key=lambda x: x.get("m_timestamp", 0), default=None)
                if latest_entry:
                    filename = latest_entry.get("display_name") or latest_entry.get("name")
                    self._current_job_file = filename

        if not filename:
            return


        file_entry = self._files_cache.get(filename.lower())
        short_name = file_entry.get("name") if file_entry else None
        thumb_path = file_entry.get("thumbnail") if file_entry else None
        if not thumb_path and short_name:
            thumb_path = f"/thumb/l/usb/{short_name}"

        # If file_entry wasn't in cache, try finding by prefix or containment
        if not thumb_path:
            for k, v in self._files_cache.items():
                if filename.lower() in k or k in filename.lower():
                    thumb_path = v.get("thumbnail")
                    short_name = v.get("name")
                    break

        if thumb_path:
            self._current_thumbnail_path = thumb_path

        # Filament detection
        fil_type = self._current_filament.get("type")
        fil_weight = self._current_filament.get("weight_g")
        fil_vol = self._current_filament.get("volume_cm3")
        fil_len = self._current_filament.get("length_mm")
        fil_cost = self._current_filament.get("cost")

        # 1. From job_data if provided by PrusaLink
        job_fil = job_data.get("filament") if isinstance(job_data, dict) else None
        if isinstance(job_fil, dict):
            if job_fil.get("length") is not None:
                fil_len = job_fil.get("length")
            if job_fil.get("volume") is not None:
                fil_vol = job_fil.get("volume")
            if job_fil.get("weight") is not None:
                fil_weight = job_fil.get("weight")
            if job_fil.get("type"):
                fil_type = job_fil.get("type")
        elif isinstance(job_fil, str):
            fil_type = job_fil

        # 2. If .bgcode file, read header directly
        is_bgcode = filename.lower().endswith(".bgcode") or (short_name and short_name.lower().endswith(".bgc"))
        if is_bgcode and short_name and (fil_weight is None or fil_len is None):
            try:
                chunk = self._client.get_file_header(ip, api_key, f"/usb/{short_name}", max_bytes=32768)
                if chunk:
                    text = chunk.decode("latin1", errors="ignore")
                    m_type = re.search(r"filament_type\s*=\s*([^\r\n;]+)", text)
                    if m_type and not fil_type:
                        fil_type = m_type.group(1).strip()

                    m_g = re.search(r"filament used \[g\]\s*=\s*([0-9.]+)", text)
                    if m_g and fil_weight is None:
                        fil_weight = float(m_g.group(1))

                    m_cm3 = re.search(r"filament used \[cm3\]\s*=\s*([0-9.]+)", text)
                    if m_cm3 and fil_vol is None:
                        fil_vol = float(m_cm3.group(1))

                    m_mm = re.search(r"filament used \[mm\]\s*=\s*([0-9.]+)", text)
                    if m_mm and fil_len is None:
                        fil_len = float(m_mm.group(1))

                    m_cost = re.search(r"filament cost\s*=\s*([0-9.]+)", text)
                    if m_cost and fil_cost is None:
                        fil_cost = float(m_cost.group(1))

            except Exception as e:
                self._logger.debug(f"Error parsing bgcode header: {e}")

        # 3. Filename regex fallback for filament material
        if not fil_type and filename:
            m_mat = re.search(r"[._-](PLA|PETG|ABS|ASA|FLEX|TPU|PC|PVB|PA|PET|HIPS|CPE|PC-BLEND)[._-]", filename, re.IGNORECASE)
            if m_mat:
                fil_type = m_mat.group(1).upper()

        fil_length_m = round(fil_len / 1000.0, 2) if fil_len is not None else None
        fil_vol_cm3 = round(fil_vol, 2) if fil_vol is not None else None
        fil_weight_g = round(fil_weight, 2) if fil_weight is not None else None

        self._current_filament = {
            "type": fil_type,
            "weight_g": fil_weight_g,
            "length_m": fil_length_m,
            "length_mm": fil_len,
            "volume_cm3": fil_vol_cm3,
            "cost": fil_cost,
        }

    def _handle_disconnected(self):
        was_online = self._prusalink_online
        self._prusalink_online = False
        self._prusalink_state = "OFFLINE"

        if was_online and (self._is_prusalink_printing or self._is_prusalink_paused):
            self._logger.info("PrusaLink went offline during print mirroring")
            self._is_prusalink_printing = False
            self._is_prusalink_paused = False

        self._prusalink_info = {
            "online": False,
            "state": "OFFLINE",
            "temp_nozzle": None,
            "target_nozzle": None,
            "temp_bed": None,
            "target_bed": None,
            "axis_x": None,
            "axis_y": None,
            "axis_z": None,
            "flow": None,
            "speed": None,
            "fan_hotend": None,
            "fan_print": None,
            "job_file": self._current_job_file,
            "progress": None,
            "time_printing": None,
            "time_remaining": None,
            "prusa_ip": None,
            "printer_name": getattr(self, "_prusa_model_name", "Prusa 3D Drucker"),
            "thumbnail_url": None,
            "thumbnail_path": None,
            "filament_type": None,
            "filament_weight_g": None,
            "filament_length_m": None,
            "filament_volume_cm3": None,
            "filament_cost": None,
            "first_layer_inspecting": False,
        }
        if hasattr(self, "_plugin_manager") and self._plugin_manager is not None:
            try:
                self._plugin_manager.send_plugin_message(self._identifier, self._prusalink_info)
            except Exception as e:
                self._logger.debug(f"Error sending plugin message: {e}")

    def _sync_to_octoprint(self, state_str: str, job_data: Dict[str, Any], telemetry_data: Dict[str, Any]):
        if not hasattr(self, "_printer") or self._printer is None:
            return

        is_printing = (state_str == "PRINTING")
        is_paused = (state_str == "PAUSED")
        was_printing = self._is_prusalink_printing
        was_paused = self._is_prusalink_paused

        self._is_prusalink_printing = is_printing
        self._is_prusalink_paused = is_paused

        # Parse job details
        file_info = job_data.get("file", {}) if isinstance(job_data.get("file"), dict) else {}
        filename = (
            file_info.get("display_name")
            or file_info.get("name")
            or self._current_job_file
            or "PrusaLink_Job.gcode"
        )
        filesize = file_info.get("size") or 0

        # Progress (0.0 to 100.0)
        progress = job_data.get("progress")
        time_printing = job_data.get("time_printing") or 0
        time_remaining = job_data.get("time_remaining")
        job_id = job_data.get("id")

        if job_id is not None:
            self._current_job_id = job_id
        if is_printing or is_paused:
            self._current_job_file = filename
            self._current_progress = progress
            self._current_time_printing = time_printing
            self._current_time_remaining = time_remaining

        dict_cls = getattr(self._printer, "_dict", dict)

        # 1. Update StateMonitor if OctoPrint's internal state monitor exists
        state_monitor = getattr(self._printer, "_stateMonitor", None)
        if state_monitor is not None:
            try:
                if is_printing or is_paused:
                    flags = dict_cls(
                        operational=True,
                        printing=is_printing,
                        cancelling=False,
                        pausing=False,
                        resuming=False,
                        finishing=False,
                        closedOrError=False,
                        error=False,
                        paused=is_paused,
                        ready=False,
                        sdReady=True,
                    )
                    state_text = "Printing" if is_printing else "Paused"
                    state_dict = dict_cls(
                        text=state_text,
                        flags=flags,
                        error="",
                    )
                    state_monitor.set_state(state_dict)

                    estimated_time = (time_printing + time_remaining) if time_remaining is not None else None
                    fil_len_mm = self._current_filament.get("length_mm")
                    fil_vol_cm3 = self._current_filament.get("volume_cm3")
                    job_dict = dict_cls(
                        file=dict_cls(
                            name=filename,
                            path=filename,
                            size=filesize,
                            origin="local",
                            date=int(time.time()),
                        ),
                        estimatedPrintTime=estimated_time,
                        lastPrintTime=None,
                        filament=dict_cls(length=fil_len_mm, volume=fil_vol_cm3),
                        user="PrusaLink",
                    )
                    state_monitor.set_job_data(job_dict)

                    if progress is not None:
                        prog_dict = dict_cls(
                            completion=float(progress),
                            filepos=None,
                            printTime=int(time_printing),
                            printTimeLeft=int(time_remaining) if time_remaining is not None else None,
                            printTimeLeftOrigin="estimate",
                        )
                        state_monitor.set_progress(prog_dict)

                elif was_printing or was_paused or state_str in ("FINISHED", "IDLE", "READY", "STOPPED"):
                    if not is_printing and not is_paused:
                        # Reset job data when returning from printing to idle
                        reset_job = dict_cls(
                            file=dict_cls(name=None, path=None, size=None, origin=None, date=None),
                            estimatedPrintTime=None,
                            lastPrintTime=time_printing if time_printing else None,
                            filament=dict_cls(length=None, volume=None),
                            user=None,
                        )
                        state_monitor.set_job_data(reset_job)
                        reset_prog = dict_cls(
                            completion=None,
                            filepos=None,
                            printTime=None,
                            printTimeLeft=None,
                            printTimeLeftOrigin=None,
                        )
                        state_monitor.set_progress(reset_prog)

                        is_op = True
                        orig_is_op = getattr(self._printer, "is_operational", lambda: True)
                        try:
                            is_op = orig_is_op()
                        except Exception:
                            pass

                        if is_op:
                            flags = dict_cls(
                                operational=True,
                                printing=False,
                                cancelling=False,
                                pausing=False,
                                resuming=False,
                                finishing=False,
                                closedOrError=False,
                                error=False,
                                paused=False,
                                ready=True,
                                sdReady=True,
                            )
                            state_dict = dict_cls(
                                text="Operational",
                                flags=flags,
                                error="",
                            )
                            state_monitor.set_state(state_dict)

                        # If serial comm is in STATE_PRINTING_FROM_SD or STATE_PRINTING, transition back to Operational
                        comm = getattr(self._printer, "_comm", None)
                        if comm is not None:
                            try:
                                if hasattr(comm, "_sdPrintingFile") and comm._sdPrintingFile is not None:
                                    comm._sdPrintingFile = None
                                if (hasattr(comm, "isSdPrinting") and comm.isSdPrinting()) or (hasattr(comm, "isPrinting") and comm.isPrinting()):
                                    comm._changeState(comm.STATE_OPERATIONAL)
                            except Exception as e:
                                self._logger.debug(f"Error resetting comm state: {e}")
            except Exception as e:
                self._logger.debug(f"Error updating StateMonitor: {e}")

        # 2. Update Z axis if reported by PrusaLink
        axis_z = telemetry_data.get("axis_z")
        if axis_z is not None:
            self._current_axis_z = axis_z
            set_z_method = getattr(self._printer, "_setCurrentZ", None)
            if set_z_method is not None:
                try:
                    set_z_method(axis_z)
                except Exception as e:
                    self._logger.debug(f"Error calling _setCurrentZ: {e}")
            elif state_monitor is not None and hasattr(state_monitor, "set_current_z"):
                try:
                    state_monitor.set_current_z(axis_z)
                except Exception as e:
                    self._logger.debug(f"Error calling set_current_z on StateMonitor: {e}")
        elif not is_printing and not is_paused:
            self._current_axis_z = None

        # 3. Synchronize Obico print job tracker and NozzleCam (First Layer AI)
        if hasattr(self, "_plugin_manager") and self._plugin_manager is not None:
            try:
                obico_plugin = self._plugin_manager.get_plugin("obico") or self._plugin_manager.get_plugin("thespaghettidetective")
                if obico_plugin and hasattr(obico_plugin, "implementation"):
                    obico_impl = obico_plugin.implementation
                    tracker = getattr(obico_impl, "_print_job_tracker", None)

                    # Determine layer height from filename or default to 0.20mm
                    layer_height = 0.2
                    if filename:
                        match = re.search(r"([0-9.]+)\s*mm", filename, re.IGNORECASE)
                        if match:
                            try:
                                lh = float(match.group(1))
                                if 0.05 <= lh <= 0.8:
                                    layer_height = lh
                            except ValueError:
                                pass

                    current_layer = 1
                    if axis_z is not None:
                        current_layer = max(1, int(round(axis_z / layer_height)))

                    if tracker is not None:
                        # Sync start timestamp so Obico displays the real elapsed time
                        tracker_ts = getattr(tracker, "current_print_ts", -1)
                        if is_printing and time_printing and isinstance(tracker_ts, (int, float)) and tracker_ts > 0:
                            expected_start_ts = int(time.time()) - int(time_printing)
                            if abs(tracker_ts - expected_start_ts) > 10:
                                tracker.current_print_ts = expected_start_ts

                        # Sync current layer height / layer number
                        if axis_z is not None:
                            tracker.current_layer_height = current_layer

                            if progress and isinstance(progress, (int, float)) and progress > 0:
                                total_layers = max(current_layer, int(round(current_layer / (float(progress) / 100.0))))
                                if getattr(tracker, "_file_metadata_cache", None) is None:
                                    tracker._file_metadata_cache = {}
                                if isinstance(tracker._file_metadata_cache, dict):
                                    tracker._file_metadata_cache.setdefault("obico", {})["totalLayerCount"] = total_layers

                    # Synchronize Obico NozzleCam (Nozzle Ninja / First Layer AI)
                    sync_nozzlecam = True
                    if hasattr(self, "_settings") and self._settings:
                        setting_val = self._settings.get(["sync_obico_nozzlecam"])
                        if setting_val is not None:
                            sync_nozzlecam = bool(setting_val)
                        else:
                            sync_nozzlecam = True

                    if sync_nozzlecam:
                        nozzlecam = getattr(obico_impl, "nozzlecam", None)
                        if nozzlecam is not None:
                            # Verify if nozzlecam config exists or try building it from Obico settings
                            has_config = getattr(nozzlecam, "nozzle_config", None) is not None
                            if not has_config and hasattr(obico_impl, "_settings"):
                                configured_camera = obico_impl._settings.get(["nozzle_camera"])
                                if configured_camera and hasattr(nozzlecam, "create_nozzlecam_config"):
                                    try:
                                        from octoprint_obico.webcam_stream import get_webcam_configs
                                        configs = get_webcam_configs(obico_impl)
                                        nozzlecam.create_nozzlecam_config(configs)
                                        has_config = getattr(nozzlecam, "nozzle_config", None) is not None
                                    except Exception:
                                        pass

                            # First layer active criteria:
                            # 1. Printer is currently PRINTING and not paused
                            # 2. Z height is within first layer boundary (0.05 <= axis_z <= layer_height * 1.5)
                            is_first_layer = False
                            if is_printing and not is_paused:
                                if axis_z is not None:
                                    is_first_layer = (0.05 <= axis_z <= (layer_height * 1.5))
                                else:
                                    is_first_layer = (progress is not None and 0.0 <= progress <= 2.0) or (time_printing is not None and time_printing <= 60)

                            if is_first_layer and has_config:
                                if not getattr(nozzlecam, "on_first_layer", False):
                                    self._logger.info("First layer printing detected via PrusaLink! Triggering Obico NozzleCam inspection...")
                                    nozzlecam.on_first_layer = True
                                    self._first_layer_inspecting = True
                                    t = threading.Thread(target=nozzlecam.start, name="OctoLink-ObicoNozzleCam")
                                    t.daemon = True
                                    t.start()
                            else:
                                if getattr(nozzlecam, "on_first_layer", False):
                                    reason = f"Z={axis_z}mm (layer > 1)" if (axis_z is not None and axis_z > (layer_height * 1.5)) else ("print ended/paused" if not is_printing or is_paused else "layer completed")
                                    self._logger.info(f"First layer finished ({reason})! Finalizing Obico NozzleCam inspection...")
                                    nozzlecam.on_first_layer = False
                                    self._first_layer_inspecting = False
            except Exception as e:
                self._logger.debug(f"Error syncing with Obico: {e}")

        # 4. Fire OctoPrint Events for plugins like Obico
        event_bus = getattr(self, "_event_bus", None)
        if event_bus is not None and Events is not None:
            try:
                if is_printing and not was_printing and not was_paused:
                    self._logger.info(f"Firing OctoPrint event: PRINT_STARTED ('{filename}')")
                    event_bus.fire(
                        Events.PRINT_STARTED,
                        {"name": filename, "path": filename, "origin": "local", "size": filesize},
                    )
                elif is_paused and not was_paused and was_printing:
                    self._logger.info("Firing OctoPrint event: PRINT_PAUSED")
                    event_bus.fire(Events.PRINT_PAUSED)
                elif is_printing and was_paused:
                    self._logger.info("Firing OctoPrint event: PRINT_RESUMED")
                    event_bus.fire(Events.PRINT_RESUMED)
                elif state_str == "FINISHED" and (was_printing or was_paused):
                    self._logger.info(f"Firing OctoPrint event: PRINT_DONE ('{filename}')")
                    event_bus.fire(
                        Events.PRINT_DONE,
                        {"name": filename, "path": filename, "origin": "local", "time": time_printing},
                    )
                elif state_str == "STOPPED" and (was_printing or was_paused):
                    self._logger.info("Firing OctoPrint event: PRINT_CANCELLED")
                    event_bus.fire(Events.PRINT_CANCELLED)
                elif state_str == "ERROR" and (was_printing or was_paused):
                    self._logger.info("Firing OctoPrint event: PRINT_FAILED")
                    event_bus.fire(Events.PRINT_FAILED, {"reason": "PrusaLink reported printer error"})

                if is_printing and progress is not None:
                    curr_prog_int = int(progress)
                    if curr_prog_int != self._last_fired_progress:
                        self._last_fired_progress = curr_prog_int
                        event_bus.fire(Events.PRINT_PROGRESS, {"progress": curr_prog_int})
            except Exception as e:
                self._logger.debug(f"Error firing event: {e}")

        # 3. Synchronize temperatures
        sync_temps = True
        if hasattr(self, "_settings") and self._settings:
            sync_temps = self._settings.get_boolean(["sync_temperatures"])

        if sync_temps:
            t_nozzle = telemetry_data.get("temp_nozzle")
            tgt_nozzle = telemetry_data.get("target_nozzle")
            t_bed = telemetry_data.get("temp_bed")
            tgt_bed = telemetry_data.get("target_bed")

            if t_nozzle is not None or t_bed is not None:
                now_ts = int(time.time())
                t_nozzle_val = float(t_nozzle) if t_nozzle is not None else 0.0
                tgt_nozzle_val = float(tgt_nozzle) if tgt_nozzle is not None else 0.0
                t_bed_val = float(t_bed) if t_bed is not None else 0.0
                tgt_bed_val = float(tgt_bed) if tgt_bed is not None else 0.0

                temp_record = {
                    "time": now_ts,
                    "tool0": {"actual": t_nozzle_val, "target": tgt_nozzle_val},
                    "bed": {"actual": t_bed_val, "target": tgt_bed_val},
                }
                self._current_temps = {
                    "tool0": {"actual": t_nozzle_val, "target": tgt_nozzle_val, "offset": 0},
                    "bed": {"actual": t_bed_val, "target": tgt_bed_val, "offset": 0},
                }

                if hasattr(self._printer, "_temps") and self._printer._temps is not None:
                    try:
                        self._printer._temps.append(temp_record)
                    except Exception as e:
                        self._logger.debug(f"Error appending to _temps: {e}")

                if state_monitor is not None and hasattr(state_monitor, "add_temperature"):
                    try:
                        state_monitor.add_temperature(dict_cls(**temp_record))
                    except Exception as e:
                        self._logger.debug(f"Error calling StateMonitor.add_temperature: {e}")

    # ~~ Job Command Forwarding

    def send_prusalink_command(self, command: str) -> Tuple[bool, str]:
        """
        Sends pause/cancel/resume command to PrusaLink.
        """
        if not hasattr(self, "_settings") or not self._settings:
            return False, "Settings not initialized"

        prusa_ip = (self._settings.get(["prusa_ip"]) or "").strip()
        prusa_api_key = (self._settings.get(["prusa_api_key"]) or "").strip()

        if not prusa_ip:
            self._logger.warning("Cannot send PrusaLink command: IP not configured")
            return False, "PrusaLink IP not configured"

        self._logger.info(f"Forwarding command '{command}' to PrusaLink at {prusa_ip}")
        success, message = self._client.send_job_command(
            ip=prusa_ip,
            api_key=prusa_api_key,
            command=command,
            job_id=self._current_job_id,
        )

        if success:
            self._logger.info(f"Command '{command}' successfully processed: {message}")
            if command.lower() in ("cancel", "stop"):
                self._is_prusalink_printing = False
                self._is_prusalink_paused = False
            elif command.lower() == "pause":
                self._is_prusalink_printing = False
                self._is_prusalink_paused = True
            elif command.lower() in ("resume", "continue"):
                self._is_prusalink_printing = True
                self._is_prusalink_paused = False
        else:
            self._logger.warning(f"Command '{command}' failed on PrusaLink: {message}")

        return success, message

    # ~~ Action Hook

    def hook_action_command(self, comm, line, action, *args, **kwargs):
        """
        Action command hook for octoprint.comm.protocol.action.
        Intercepts action commands (e.g. // action:cancel, // action:pause).
        """
        clean_action = (action or "").strip().lower()
        if clean_action in ("cancel", "pause", "resume"):
            self._logger.info(f"Action hook intercepted '{clean_action}', forwarding to PrusaLink")
            self.send_prusalink_command(clean_action)
        return (action,)

    # ~~ Additional State Data Hook

    def hook_additional_state_data(self, *args, **kwargs):
        """
        Provides custom telemetry data in OctoPrint printer state.
        """
        return {
            "prusalink_bridge": {
                "online": self._prusalink_online,
                "state": self._prusalink_state,
                "printing": self._is_prusalink_printing,
                "paused": self._is_prusalink_paused,
                "job_id": self._current_job_id,
                "file": self._current_job_file,
                "progress": self._current_progress,
            }
        }

    # ~~ PrinterInterface Wrapping (Obico & 3rd-Party Compatibility)

    def _wrap_printer_methods(self):
        if not hasattr(self, "_printer") or self._printer is None:
            self._logger.warning("PrinterInterface not available on plugin, skipping method wrapping")
            return

        orig_is_printing = self._printer.is_printing
        orig_is_paused = self._printer.is_paused
        orig_is_operational = self._printer.is_operational
        orig_get_state_string = self._printer.get_state_string
        orig_get_state_id = self._printer.get_state_id
        orig_pause_print = self._printer.pause_print
        orig_cancel_print = self._printer.cancel_print
        orig_resume_print = getattr(self._printer, "resume_print", None)
        orig_update_progress_data = getattr(self._printer, "_updateProgressData", None)
        orig_get_current_data = self._printer.get_current_data
        orig_get_current_temperatures = self._printer.get_current_temperatures

        plugin = self

        def wrapped_is_printing(*args, **kwargs):
            if plugin._is_prusalink_printing:
                return True
            if plugin._prusalink_online and plugin._prusalink_state in ("FINISHED", "IDLE", "READY", "STOPPED"):
                return False
            return orig_is_printing(*args, **kwargs)

        def wrapped_is_paused(*args, **kwargs):
            if plugin._is_prusalink_paused:
                return True
            return orig_is_paused(*args, **kwargs)

        def wrapped_is_operational(*args, **kwargs):
            if plugin._is_prusalink_printing or plugin._is_prusalink_paused:
                return True
            return orig_is_operational(*args, **kwargs)

        def wrapped_get_state_string(*args, **kwargs):
            if plugin._is_prusalink_printing:
                return "Printing"
            elif plugin._is_prusalink_paused:
                return "Paused"
            if plugin._prusalink_online and plugin._prusalink_state in ("FINISHED", "IDLE", "READY", "STOPPED"):
                base_str = orig_get_state_string(*args, **kwargs)
                if base_str in ("Printing", "Printing from SD"):
                    return "Operational"
                return base_str
            return orig_get_state_string(*args, **kwargs)

        def wrapped_get_state_id(*args, **kwargs):
            if plugin._is_prusalink_printing:
                return "PRINTING"
            elif plugin._is_prusalink_paused:
                return "PAUSED"
            if plugin._prusalink_online and plugin._prusalink_state in ("FINISHED", "IDLE", "READY", "STOPPED"):
                base_id = orig_get_state_id(*args, **kwargs)
                if base_id in ("PRINTING", "PRINTING_FROM_SD"):
                    return "OPERATIONAL"
                return base_id
            return orig_get_state_id(*args, **kwargs)

        def wrapped_pause_print(user=None, *args, **kwargs):
            plugin._logger.info("pause_print invoked on PrinterInterface")
            if plugin._is_prusalink_printing or plugin._is_prusalink_paused:
                plugin.send_prusalink_command("pause")
            try:
                return orig_pause_print(user=user, *args, **kwargs)
            except Exception as e:
                plugin._logger.debug(f"Original pause_print raised: {e}")

        def wrapped_cancel_print(user=None, *args, **kwargs):
            plugin._logger.info("cancel_print invoked on PrinterInterface")
            if plugin._is_prusalink_printing or plugin._is_prusalink_paused:
                plugin.send_prusalink_command("cancel")
            try:
                return orig_cancel_print(user=user, *args, **kwargs)
            except Exception as e:
                plugin._logger.debug(f"Original cancel_print raised: {e}")

        def wrapped_resume_print(user=None, *args, **kwargs):
            plugin._logger.info("resume_print invoked on PrinterInterface")
            if plugin._is_prusalink_paused:
                plugin.send_prusalink_command("resume")
            if orig_resume_print is not None:
                try:
                    return orig_resume_print(user=user, *args, **kwargs)
                except Exception as e:
                    plugin._logger.debug(f"Original resume_print raised: {e}")

        def wrapped_update_progress_data(
            completion=None,
            filepos=None,
            printTime=None,
            printTimeLeft=None,
            printTimeLeftOrigin=None,
            *args,
            **kwargs,
        ):
            if plugin._is_prusalink_printing:
                if plugin._current_progress is not None:
                    completion = plugin._current_progress / 100.0
                if plugin._current_time_printing is not None:
                    printTime = int(plugin._current_time_printing)
                if plugin._current_time_remaining is not None:
                    printTimeLeft = int(plugin._current_time_remaining)
                    printTimeLeftOrigin = "estimate"
            if orig_update_progress_data is not None:
                return orig_update_progress_data(
                    completion=completion,
                    filepos=filepos,
                    printTime=printTime,
                    printTimeLeft=printTimeLeft,
                    printTimeLeftOrigin=printTimeLeftOrigin,
                    *args,
                    **kwargs,
                )

        def wrapped_get_current_data(*args, **kwargs):
            data = orig_get_current_data(*args, **kwargs)
            if plugin._is_prusalink_printing or plugin._is_prusalink_paused:
                if isinstance(data, dict):
                    data = dict(data)
                    st = dict(data.get("state", {}))
                    flags = dict(st.get("flags", {}))
                    flags["printing"] = plugin._is_prusalink_printing
                    flags["paused"] = plugin._is_prusalink_paused
                    flags["operational"] = True
                    flags["ready"] = not plugin._is_prusalink_printing and not plugin._is_prusalink_paused
                    st["flags"] = flags
                    st["text"] = "Printing" if plugin._is_prusalink_printing else ("Paused" if plugin._is_prusalink_paused else st.get("text", "Operational"))
                    data["state"] = st

                    if plugin._current_progress is not None and "progress" in data and isinstance(data["progress"], dict):
                        prog = dict(data["progress"])
                        prog["completion"] = plugin._current_progress
                        prog["printTime"] = plugin._current_time_printing
                        prog["printTimeLeft"] = plugin._current_time_remaining
                        data["progress"] = prog

                    if plugin._current_job_file is not None and "job" in data and isinstance(data["job"], dict):
                        job_d = dict(data["job"])
                        file_d = dict(job_d.get("file", {}))
                        file_d["name"] = plugin._current_job_file
                        file_d["origin"] = "local"
                        job_d["file"] = file_d
                        data["job"] = job_d

                    if plugin._current_axis_z is not None:
                        data["currentZ"] = plugin._current_axis_z
            elif plugin._prusalink_online and plugin._prusalink_state in ("FINISHED", "IDLE", "READY", "STOPPED"):
                if isinstance(data, dict):
                    data = dict(data)
                    st = dict(data.get("state", {}))
                    flags = dict(st.get("flags", {}))
                    if flags.get("printing"):
                        flags["printing"] = False
                        flags["ready"] = True
                        st["flags"] = flags
                        if st.get("text") in ("Printing", "Printing from SD"):
                            st["text"] = "Operational"
                        data["state"] = st
            return data

        def wrapped_get_current_temperatures(*args, **kwargs):
            temps = orig_get_current_temperatures(*args, **kwargs)
            if plugin._current_temps:
                # If OctoPrint has no active temperatures or is offline, inject PrusaLink temps
                if not temps or all(v.get("actual") == 0 and v.get("target") == 0 for v in temps.values() if isinstance(v, dict)):
                    return plugin._current_temps
            return temps

        # Store originals
        self._orig_printer_methods = {
            "is_printing": orig_is_printing,
            "is_paused": orig_is_paused,
            "is_operational": orig_is_operational,
            "get_state_string": orig_get_state_string,
            "get_state_id": orig_get_state_id,
            "pause_print": orig_pause_print,
            "cancel_print": orig_cancel_print,
            "get_current_data": orig_get_current_data,
            "get_current_temperatures": orig_get_current_temperatures,
        }
        if orig_resume_print is not None:
            self._orig_printer_methods["resume_print"] = orig_resume_print
        if orig_update_progress_data is not None:
            self._orig_printer_methods["_updateProgressData"] = orig_update_progress_data

        # Apply wrappers
        self._printer.is_printing = wrapped_is_printing
        self._printer.is_paused = wrapped_is_paused
        self._printer.is_operational = wrapped_is_operational
        self._printer.get_state_string = wrapped_get_state_string
        self._printer.get_state_id = wrapped_get_state_id
        self._printer.pause_print = wrapped_pause_print
        self._printer.cancel_print = wrapped_cancel_print
        self._printer.resume_print = wrapped_resume_print
        if orig_update_progress_data is not None:
            self._printer._updateProgressData = wrapped_update_progress_data
        self._printer.get_current_data = wrapped_get_current_data
        self._printer.get_current_temperatures = wrapped_get_current_temperatures
        self._logger.info("PrinterInterface methods successfully wrapped for PrusaLink mirroring")

    def _unwrap_printer_methods(self):
        if hasattr(self, "_orig_printer_methods") and hasattr(self, "_printer") and self._printer:
            for name, method in self._orig_printer_methods.items():
                try:
                    setattr(self._printer, name, method)
                except Exception as e:
                    self._logger.debug(f"Error unwrapping {name}: {e}")
            self._orig_printer_methods.clear()
            self._logger.info("PrinterInterface methods restored to originals")

    # ~~ Software Update Hook

    def get_update_information(self):
        current_version = getattr(self, "_plugin_version", __version__)
        return {
            "prusalink_bridge": {
                "displayName": "OctoPrint-PrusaLink-Bridge",
                "displayVersion": current_version,
                "type": "github_release",
                "user": "Snake4you",
                "repo": "OctoLink",
                "current": current_version,
                "pip": "https://github.com/Snake4you/OctoLink/archive/{target_version}.zip",
            }
        }


# Plugin registration
__plugin_name__ = "PrusaLink Bridge"
__plugin_version__ = __version__
__plugin_pythoncompat__ = ">=3.7,<4"
__plugin_implementation__ = PrusaLinkBridgePlugin()
__plugin_hooks__ = {
    "octoprint.comm.protocol.action": __plugin_implementation__.hook_action_command,
    "octoprint.printer.additional_state_data": __plugin_implementation__.hook_additional_state_data,
    "octoprint.plugin.softwareupdate.check_config": __plugin_implementation__.get_update_information,
}


def __plugin_load__():
    global __plugin_implementation__
    global __plugin_hooks__
    __plugin_implementation__ = PrusaLinkBridgePlugin()
    __plugin_hooks__ = {
        "octoprint.comm.protocol.action": __plugin_implementation__.hook_action_command,
        "octoprint.printer.additional_state_data": __plugin_implementation__.hook_additional_state_data,
        "octoprint.plugin.softwareupdate.check_config": __plugin_implementation__.get_update_information,
    }
