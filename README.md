# OctoPrint-PrusaLink-Bridge

Ein OctoPrint-Plugin zur nahtlosen Spiegelung von Telemetrie-, Temperatur- und Druckstatusdaten eines **Prusa MK3.5, MK4, XL, CORE One** (und weiteren PrusaLink-fähigen Druckern) direkt in OctoPrint.

---

## 🎯 Zweck & Motivation

Wird ein Druck direkt am Drucker über USB-Stick oder PrusaLink gestartet, erfährt ein separates OctoPrint normalerweise nichts davon, wenn es nicht aktiv über die serielle Schnittstelle druckt.

Drittanbieter-Plugins wie **Obico (The Spaghetti Detective)** sind darauf angewiesen, dass OctoPrint den Druckstatus als aktiv erkennt (`is_printing() == True`), um die KI-Fehldruckerkennung (Spaghetti-Detektion) und den automatischen Druckabbruch bzw. die Pause zu aktivieren.

**OctoPrint-PrusaLink-Bridge** löst dieses Problem:
1. **Status- & Telemetrie-Spiegelung:** Fragt die lokale PrusaLink-REST-API (`/api/v1/status` und `/api/v1/job`) zyklisch im Hintergrund ab.
2. **Virtueller Druckstatus:** Spiegelt den Status (`PRINTING`, `PAUSED`, `FINISHED`, `IDLE`) sowie Dateiname, Fortschritt in Prozent und verbleibende Druckzeit in OctoPrints Druckerschnittstelle und den `StateMonitor`.
3. **Echtzeit-Temperaturgraph:** Überträgt Hotend- und Druckbett-Temperaturen in OctoPrint, sodass der Temperatur-Tab live aktualisiert wird.
4. **Befehlsweiterleitung (Abbruch & Pause):** Fängt Abbruch- (`cancel`) oder Pause-Befehle (`pause`) von Obico oder der OctoPrint-Weboberfläche ab und sendet sie per HTTP POST an PrusaLink weiter (`POST /api/v1/job` bzw. REST-Fallback).

---

## 🚀 Installation

Das Plugin kann direkt über den OctoPrint Plugin Manager via URL oder über die Befehlszeile installiert werden:

```bash
# In der OctoPrint-Virtualenv:
pip install .
```

Oder via Git-URL:
```bash
pip install https://github.com/snake/OctoPrint-PrusaLink-Bridge/archive/master.zip
```

---

## ⚙️ Konfiguration

Navigiere in OctoPrint zu **Einstellungen > PrusaLink Bridge**:

| Einstellung | Typ | Standard | Beschreibung |
|---|---|---|---|
| **PrusaLink IP / Hostname** | Text | *leer* | Lokale IP-Adresse oder Hostname des Druckers (z. B. `192.168.1.150` oder `prusa.local`). |
| **PrusaLink API-Key** | Passwort | *leer* | API-Schlüssel aus dem Druckermenü (**Einstellungen > Netzwerk > PrusaLink**). |
| **Polling-Intervall** | Zahl | `2.0` | Abfrageintervall in Sekunden (0.5 bis 60 Sekunden). |
| **Temperaturen spiegeln** | Checkbox | `True` | Ob Nozzle- und Bett-Temperaturen in OctoPrint aktualisiert werden sollen. |

> **Tipp:** Über den Button **"Verbindung testen"** kann direkt in den Einstellungen überprüft werden, ob IP und API-Key korrekt sind und der Drucker antwortet.

---

## 🏗️ Architektur & Funktionsweise

```
+-------------------------------------------------------------+
|                     Prusa 3D-Drucker                        |
|           (MK3.5 / MK4 / XL / CORE One mit PrusaLink)       |
+------------------------------+------------------------------+
                               |
                   HTTP GET /api/v1/status
                   HTTP GET /api/v1/job
                   HTTP POST /api/v1/job {"command": ...}
                               |
                               v
+-------------------------------------------------------------+
|                 OctoPrint-PrusaLink-Bridge                  |
|                                                             |
|  +-------------------------------------------------------+  |
|  | Background Worker Thread (Daemon)                     |  |
|  | - Fragt zyklisch Status, Job & Telemetrie ab          |  |
|  | - Unterdrückt Log-Spam bei Verbindungsabbrüchen       |  |
|  +---------------------------+---------------------------+  |
|                              |                              |
|  +---------------------------v---------------------------+  |
|  | Status- & Event-Synchronisation                       |  |
|  | - Aktualisiert StateMonitor & _temps                 |  |
|  | - Feuert Events: PRINT_STARTED, PRINT_PROGRESS, ...   |  |
|  +---------------------------+---------------------------+  |
|                              |                              |
|  +---------------------------v---------------------------+  |
|  | PrinterInterface Wrapping & Action Hook               |  |
|  | - is_printing() -> True bei PrusaLink-Druck           |  |
|  | - pause_print() / cancel_print() -> POST an PrusaLink |  |
|  +-------------------------------------------------------+  |
+------------------------------+------------------------------+
                               |
                               v
+-------------------------------------------------------------+
|                   Drittanbieter-Plugins                     |
|           Obico (The Spaghetti Detective) / Web-UI          |
|  - Erkennt is_printing() == True                            |
|  - Startet Webcam-Analyse & Fehldruck-Erkennung             |
|  - Pausiert/Bricht Druck bei Fehler über OctoPrint ab       |
+-------------------------------------------------------------+
```

---

## 🛡️ Obico-Kompatibilität im Detail

1. **Druckerkennung:** Obico prüft in regelmäßigen Abständen `self._printer.is_printing()`. Sobald PrusaLink den Status `PRINTING` meldet, liefert `is_printing()` den Wert `True` zurück.
2. **Event-Trigger:** Das Plugin feuert die OctoPrint-Events `Events.PRINT_STARTED`, `Events.PRINT_PROGRESS`, `Events.PRINT_PAUSED`, `Events.PRINT_RESUMED` und `Events.PRINT_DONE`.
3. **Automatischer Abbruch bei Spaghetti-Erkennung:** Wenn Obico einen Fehldruck erkennt und die automatische Pause bzw. den Abbruch auslöst, ruft Obico `printer.pause_print()` oder `printer.cancel_print()` auf. Die Bridge fängt diesen Methodenaufruf ab und leitet ihn unmittelbar per REST an PrusaLink weiter (`POST /api/v1/job` mit `{"command": "pause"}` bzw. `{"command": "cancel"}`).

---

## 🧪 Tests

Die Unittests überprüfen:
- HTTP REST Client (Status, Job, Commands, Timeouts)
- Status- und Telemetrie-Parsing (OpenAPI & Legacy-Fallback)
- PrinterInterface-Wrapping und Obico-Kompatibilität (`is_printing()`, `pause_print()`, `cancel_print()`)
- Event-Emission und Log-Spam-Vermeidung

Führe die Tests aus mit:
```bash
python3 -m unittest discover tests
```

---

## 📄 Lizenz

Dieses Plugin steht unter der **AGPLv3** Lizenz.
