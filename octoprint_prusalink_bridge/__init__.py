# coding=utf-8
from __future__ import absolute_import

import logging
import threading
import time
from typing import Any, Dict, Optional, Tuple

import requests

try:
    import octoprint.plugin
    from octoprint.events import Events
except ImportError:
    # Fallback to allow importing outside of full OctoPrint environment (e.g. unit tests)
    octoprint = None
    Events = None


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
            "User-Agent": "OctoPrint-PrusaLink-Bridge/0.1.0",
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

        # Saved original printer methods for clean unwrap
        self._orig_printer_methods = {}

    # ~~ SettingsPlugin mixin

    def get_settings_defaults(self):
        return {
            "prusa_ip": "",
            "prusa_api_key": "",
            "poll_interval": 2.0,
            "sync_temperatures": True,
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
                "custom_bindings": False,
            }
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

        telemetry_dict = {
            "temp_nozzle": nozzle_actual,
            "target_nozzle": nozzle_target,
            "temp_bed": bed_actual,
            "target_bed": bed_target,
        }

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

        # Synchronize into OctoPrint
        self._sync_to_octoprint(state_str, job_data, telemetry_dict)

    def _handle_disconnected(self):
        was_online = self._prusalink_online
        self._prusalink_online = False
        self._prusalink_state = "OFFLINE"

        if was_online and (self._is_prusalink_printing or self._is_prusalink_paused):
            self._logger.info("PrusaLink went offline during print mirroring")
            self._is_prusalink_printing = False
            self._is_prusalink_paused = False

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
                    ready=(not is_printing and not is_paused),
                    sdReady=True,
                )
                state_text = "Printing" if is_printing else ("Paused" if is_paused else "Operational")
                state_dict = dict_cls(
                    text=state_text,
                    flags=flags,
                    error="",
                )
                state_monitor.set_state(state_dict)

                if is_printing or is_paused:
                    estimated_time = (time_printing + time_remaining) if time_remaining is not None else None
                    job_dict = dict_cls(
                        file=dict_cls(
                            name=filename,
                            path=filename,
                            size=filesize,
                            origin="sdcard",
                            date=int(time.time()),
                        ),
                        estimatedPrintTime=estimated_time,
                        lastPrintTime=None,
                        filament=dict_cls(length=None, volume=None),
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

                elif state_str in ("FINISHED", "IDLE", "STOPPED", "READY"):
                    if state_str == "FINISHED" and progress is not None:
                        prog_dict = dict_cls(
                            completion=100.0,
                            filepos=None,
                            printTime=int(time_printing),
                            printTimeLeft=0,
                            printTimeLeftOrigin="estimate",
                        )
                        state_monitor.set_progress(prog_dict)
                    else:
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
            except Exception as e:
                self._logger.debug(f"Error updating StateMonitor: {e}")

        # 2. Fire OctoPrint Events for plugins like Obico
        event_bus = getattr(self, "_event_bus", None)
        if event_bus is not None and Events is not None:
            try:
                if is_printing and not was_printing and not was_paused:
                    self._logger.info(f"Firing OctoPrint event: PRINT_STARTED ('{filename}')")
                    event_bus.fire(
                        Events.PRINT_STARTED,
                        {"name": filename, "path": filename, "origin": "sdcard", "size": filesize},
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
                        {"name": filename, "path": filename, "origin": "sdcard", "time": time_printing},
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
        orig_get_current_data = self._printer.get_current_data
        orig_get_current_temperatures = self._printer.get_current_temperatures

        plugin = self

        def wrapped_is_printing(*args, **kwargs):
            if plugin._is_prusalink_printing:
                return True
            return orig_is_printing(*args, **kwargs)

        def wrapped_is_paused(*args, **kwargs):
            if plugin._is_prusalink_paused:
                return True
            return orig_is_paused(*args, **kwargs)

        def wrapped_is_operational(*args, **kwargs):
            if plugin._prusalink_online:
                return True
            return orig_is_operational(*args, **kwargs)

        def wrapped_get_state_string(*args, **kwargs):
            if plugin._is_prusalink_printing:
                return "Printing"
            elif plugin._is_prusalink_paused:
                return "Paused"
            elif plugin._prusalink_online and not orig_is_operational(*args, **kwargs):
                return "Operational"
            return orig_get_state_string(*args, **kwargs)

        def wrapped_get_state_id(*args, **kwargs):
            if plugin._is_prusalink_printing:
                return "PRINTING"
            elif plugin._is_prusalink_paused:
                return "PAUSED"
            elif plugin._prusalink_online and not orig_is_operational(*args, **kwargs):
                return "OPERATIONAL"
            return orig_get_state_id(*args, **kwargs)

        def wrapped_pause_print(user=None, *args, **kwargs):
            plugin._logger.info("pause_print invoked on PrinterInterface")
            if plugin._is_prusalink_printing or plugin._is_prusalink_paused or plugin._prusalink_online:
                plugin.send_prusalink_command("pause")
            try:
                return orig_pause_print(user=user, *args, **kwargs)
            except Exception as e:
                plugin._logger.debug(f"Original pause_print raised: {e}")

        def wrapped_cancel_print(user=None, *args, **kwargs):
            plugin._logger.info("cancel_print invoked on PrinterInterface")
            if plugin._is_prusalink_printing or plugin._is_prusalink_paused or plugin._prusalink_online:
                plugin.send_prusalink_command("cancel")
            try:
                return orig_cancel_print(user=user, *args, **kwargs)
            except Exception as e:
                plugin._logger.debug(f"Original cancel_print raised: {e}")

        def wrapped_resume_print(user=None, *args, **kwargs):
            plugin._logger.info("resume_print invoked on PrinterInterface")
            if plugin._is_prusalink_paused or plugin._prusalink_online:
                plugin.send_prusalink_command("resume")
            if orig_resume_print is not None:
                try:
                    return orig_resume_print(user=user, *args, **kwargs)
                except Exception as e:
                    plugin._logger.debug(f"Original resume_print raised: {e}")

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
                        file_d["origin"] = "sdcard"
                        job_d["file"] = file_d
                        data["job"] = job_d
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

        # Apply wrappers
        self._printer.is_printing = wrapped_is_printing
        self._printer.is_paused = wrapped_is_paused
        self._printer.is_operational = wrapped_is_operational
        self._printer.get_state_string = wrapped_get_state_string
        self._printer.get_state_id = wrapped_get_state_id
        self._printer.pause_print = wrapped_pause_print
        self._printer.cancel_print = wrapped_cancel_print
        self._printer.resume_print = wrapped_resume_print
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
        return {
            "prusalink_bridge": {
                "displayName": "OctoPrint-PrusaLink-Bridge",
                "displayVersion": self._plugin_version if hasattr(self, "_plugin_version") else "0.1.0",
                "type": "github_release",
                "user": "snake",
                "repo": "OctoPrint-PrusaLink-Bridge",
                "current": self._plugin_version if hasattr(self, "_plugin_version") else "0.1.0",
                "pip": "https://github.com/snake/OctoPrint-PrusaLink-Bridge/archive/{target_version}.zip",
            }
        }


# Plugin registration
__plugin_name__ = "PrusaLink Bridge"
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
