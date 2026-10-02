# OctoLink (OctoPrint-PrusaLink-Bridge)

[![License: AGPL v3](https://img.shields.io/badge/License-AGPLv3-blue.svg)](LICENSE)
[![Python: 3.7+](https://img.shields.io/badge/python-3.7+-brightgreen.svg)](https://www.python.org/)
[![OctoPrint](https://img.shields.io/badge/OctoPrint-1.4.0+-red.svg)](https://octoprint.org/)
[![PrusaLink](https://img.shields.io/badge/PrusaLink-MK3.5%20%7C%20MK4%20%7C%20XL%20%7C%20CORE%20One-orange.svg)](https://prusa3d.com)
[![Tests](https://img.shields.io/badge/tests-passing-brightgreen.svg)](tests/)

Seamlessly mirror print status, telemetry, temperatures, and job progress from **PrusaLink-enabled 3D printers** (Prusa MK3.5, MK4, MK4S, XL, CORE One, MINI+) into **OctoPrint** — enabling full compatibility with plugins like **Obico (The Spaghetti Detective)** without connecting via a serial USB cable.

---

## 💡 The Problem & The Solution

### The Problem
When you start a print locally on a modern Prusa printer (via USB flash drive or PrusaConnect/PrusaLink), a standalone OctoPrint instance running on a Raspberry Pi knows nothing about it. Because OctoPrint is not driving the printer over USB serial, its state remains `OPERATIONAL` or `IDLE`.

As a result:
- **Obico (The Spaghetti Detective)** does not know a print is active (`is_printing() == False`) and **will not run AI spaghetti detection**.
- OctoPrint's temperature graph remains blank or frozen.
- Automated failure detection, pause, and cancel actions cannot be triggered.

### The Solution: OctoLink
**OctoLink** acts as a virtual telemetry and control bridge between your Prusa printer's local REST API and OctoPrint:
1. 📡 **Background Telemetry Polling:** Fetches `/api/v1/status` and `/api/v1/job` in the background.
2. 🔄 **State Synchronization:** Reports printer state (`PRINTING`, `PAUSED`, `FINISHED`, `IDLE`), print filename, progress percentage, and time remaining directly into OctoPrint's `StateMonitor`.
3. 🌡️ **Live Temperatures:** Injects current hotend and heatbed temperatures into OctoPrint's temperature history graph.
4. 🤖 **Obico AI Safety Compatibility:** Overrides `printer.is_printing()` so Obico immediately starts AI spaghetti monitoring when a print begins.
5. 🛑 **Remote Command Relay:** Intercepts OctoPrint/Obico `pause` and `cancel` calls and forwards them via HTTP POST to PrusaLink, safely halting the printer upon AI failure detection.

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                 Prusa 3D Printer (PrusaLink)                │
│         (MK3.5 / MK4 / MK4S / XL / CORE One / MINI+)        │
└──────────────────────────────┬──────────────────────────────┘
                               │
                HTTP GET  /api/v1/status
                HTTP GET  /api/v1/job
                HTTP POST /api/v1/job {"command": ...}
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                  OctoLink Bridge Plugin                     │
│                                                             │
│  ┌───────────────────────────────────────────────────────┐  │
│  │ Background Worker Thread (Daemon)                     │  │
│  │ • Queries PrusaLink REST API periodically             │  │
│  │ • Intelligent error backoff (no log spam)             │  │
│  └───────────────────────────┬───────────────────────────┘  │
│                              │                              │
│  ┌───────────────────────────▼───────────────────────────┐  │
│  │ Status & Telemetry Ingestion                          │  │
│  │ • Updates OctoPrint StateMonitor & Temperatures       │  │
│  │ • Emits native OctoPrint Events (PrintStarted, etc.)  │  │
│  └───────────────────────────┬───────────────────────────┘  │
│                              │                              │
│  ┌───────────────────────────▼───────────────────────────┐  │
│  │ PrinterInterface Wrapper & Command Interceptor        │  │
│  │ • is_printing() -> True during PrusaLink prints       │  │
│  │ • pause_print() / cancel_print() -> Forward to Prusa  │  │
│  └───────────────────────────────────────────────────────┘  │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│             Third-Party Plugins & Integrations              │
│          Obico (The Spaghetti Detective) / OctoApp          │
│  • Detects is_printing() == True                            │
│  • Activates webcam AI monitoring                           │
│  • Safely triggers pause / cancel upon failure detection    │
└─────────────────────────────────────────────────────────────┘
```

---

## 🖨️ Supported Printers

Tested and fully compatible with all Prusa printers running **PrusaLink**:
- **Original Prusa MK4 / MK4S**
- **Original Prusa MK3.5**
- **Original Prusa XL**
- **Original Prusa CORE One**
- **Original Prusa MINI / MINI+** (with PrusaLink firmware)

---

## 🚀 Installation

### Option 1: Via OctoPrint Plugin Manager (Recommended)
1. Open your OctoPrint web interface.
2. Go to **Settings (Wrench icon) > Plugin Manager > Get More...**
3. Under **...from URL**, paste:
   ```text
   https://github.com/Snake4you/OctoLink/archive/refs/heads/main.zip
   ```
4. Click **Install**.
5. Restart OctoPrint when prompted.

### Option 2: Via OctoPrint Virtualenv CLI
SSH into your OctoPrint host (e.g., Raspberry Pi) and run:
```bash
source ~/oprint/bin/activate
pip install https://github.com/Snake4you/OctoLink/archive/refs/heads/main.zip
octoprint restart
```

---

## ⚙️ Configuration

Navigate to **OctoPrint Settings > PrusaLink Bridge**:

| Setting | Type | Default | Description |
|---|---|---|---|
| **PrusaLink IP / Hostname** | Text | *empty* | IP address or local hostname of your printer (e.g. `192.168.1.150` or `mk4.local`). |
| **PrusaLink API-Key** | Password | *empty* | API key found in the printer menu (**Settings > Network > PrusaLink**). |
| **Polling Interval** | Float | `2.0` | Refresh interval in seconds (between 0.5 and 60.0). |
| **Mirror Temperatures** | Boolean | `True` | Update hotend and bed temperatures in OctoPrint graphs. |

> 💡 **Connection Test:** Click the **"Test Connection"** button in the settings panel to verify IP reachability, authentication, and printer response before saving.

---

## 🛡️ Obico Integration Details

When using **Obico (The Spaghetti Detective)** alongside OctoLink:
1. **Print Detection:** Obico periodically queries `printer.is_printing()`. As soon as PrusaLink reports status `PRINTING`, OctoLink answers `True`.
2. **Event Lifecycle:** OctoLink fires standard OctoPrint events:
   - `Events.PRINT_STARTED`
   - `Events.PRINT_PROGRESS`
   - `Events.PRINT_PAUSED` / `Events.PRINT_RESUMED`
   - `Events.PRINT_DONE` / `Events.PRINT_FAILED` / `Events.PRINT_CANCELLED`
3. **Automated Interventions:** If Obico's AI detects a print failure (spaghetti, detachment, layer shift) and commands a pause or cancel, OctoLink intercepts `printer.pause_print()` or `printer.cancel_print()` and sends:
   ```http
   POST /api/v1/job
   Content-Type: application/json
   {"command": "pause"}  (or "cancel")
   ```
   directly to your Prusa printer over your local network.

---

## 🧪 Testing & Development

Run the complete test suite locally:

```bash
python3 -m unittest discover tests
```

The automated test suite verifies:
- REST client communication (API endpoints, timeouts, authentication headers)
- OpenAPI and legacy telemetry payload parsing
- `PrinterInterface` method wrapping (`is_printing()`, `pause_print()`, `cancel_print()`)
- Event dispatching and rate-limited logging

---

## 📄 License

This project is licensed under the **AGPLv3** (GNU Affero General Public License v3). See the [LICENSE](LICENSE) file for details.

---

<details>
<summary>🇩🇪 Deutsche Dokumentation (Hier klicken zum Ausklappen)</summary>

### Zweck & Motivation
Wird ein Druck direkt am Drucker (über USB-Stick oder PrusaLink/PrusaConnect) gestartet, erfährt ein separates OctoPrint normalerweise nichts davon, wenn es nicht aktiv über die serielle Schnittstelle druckt.

Drittanbieter-Plugins wie **Obico (The Spaghetti Detective)** sind darauf angewiesen, dass OctoPrint den Druckstatus als aktiv erkennt (`is_printing() == True`), um die KI-Fehldruckerkennung (Spaghetti-Detektion) und den automatischen Druckabbruch bzw. die Pause zu aktivieren.

**OctoLink** schließt diese Lücke:
1. **Status- & Telemetrie-Spiegelung:** Fragt die PrusaLink-REST-API (`/api/v1/status` und `/api/v1/job`) zyklisch im Hintergrund ab.
2. **Virtueller Druckstatus:** Überträgt Status (`PRINTING`, `PAUSED`, `FINISHED`, `IDLE`), Dateiname, Fortschritt in Prozent und verbleibende Druckzeit in OctoPrints StateMonitor.
3. **Echtzeit-Temperaturgraph:** Überträgt Hotend- und Druckbett-Temperaturen in OctoPrint.
4. **Befehlsweiterleitung (Abbruch & Pause):** Fängt Abbruch- (`cancel`) oder Pause-Befehle (`pause`) von Obico oder der OctoPrint-Weboberfläche ab und leitet sie per HTTP POST an PrusaLink weiter.

### Installation
In OctoPrint unter **Einstellungen > Plugin-Manager > Mehr... > Aus URL**:
```text
https://github.com/Snake4you/OctoLink/archive/refs/heads/main.zip
```

### Konfiguration
Unter **Einstellungen > PrusaLink Bridge**:
- **IP-Adresse / Hostname:** Lokale IP des Druckers (z. B. `192.168.1.150`).
- **API-Key:** Im Druckermenü unter **Einstellungen > Netzwerk > PrusaLink** ablesbar.
- Verbindung per **"Verbindung testen"** prüfen.

</details>
