# WLAN-Diagnose (HP-Notebooks)

Offline-Werkzeug, das WLAN-Probleme unter Windows 10/11 analysiert und automatisch repariert.
Details und Aktionsbaum: [PLAN.md](PLAN.md).

## Starten
```bat
:: GUI (Python 3.10+ mit Tkinter, keine weiteren Pakete nötig)
python -m wlandiag

:: Demo ohne echte Systemzugriffe (läuft auch unter Linux/macOS)
python -m wlandiag --demo

:: Ohne Oberfläche
python -m wlandiag --cli analyse
python -m wlandiag --cli troubleshoot [--invasive]
python -m wlandiag --cli tree
```
Reparaturen (Fix, Troubleshooting) brauchen Administratorrechte. Die GUI bietet dafür einen Neustart per UAC an.

## Als EXE bauen
`build.bat` auf einem Windows-Rechner ausführen. Ergebnis: `dist\WLAN-Diagnose.exe`
(eine Datei, fordert beim Start Adminrechte an).

## Tests
```
python -m unittest discover -s tests
```

## Aufbau
| Datei | Inhalt |
|---|---|
| `wlandiag/gui.py` | dunkle Tkinter-Oberfläche |
| `wlandiag/engine.py` | Analyse / Fix / Troubleshooting |
| `wlandiag/tree.py` | Aktionsbaum und Reparaturliste |
| `wlandiag/checks.py` | einzelne Prüfungen |
| `wlandiag/probe_windows.py` | lesende Windows-Abfragen |
| `wlandiag/actions_windows.py` | Reparaturen |
| `wlandiag/demo.py` | simuliertes Gerät für `--demo` |

Protokolle: `%LOCALAPPDATA%\WLAN-Diagnose\logs`.
