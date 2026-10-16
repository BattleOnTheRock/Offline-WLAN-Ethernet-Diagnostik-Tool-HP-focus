# WLAN-Diagnosetool für HP-Laptops: Plan

## Ziel
Ein Werkzeug, das WLAN-Probleme auf HP-Notebooks (Windows 10/11) selbstständig und **offline** analysiert,
Hardware- und Softwareursachen auseinanderhält und bekannte Probleme automatisch repariert. Was sich nicht
automatisch beheben lässt, endet in einem konkreten manuellen Schritt.

## Oberfläche
- Dunkel und minimal, ein Fenster.
- **Mitte:** Terminal-Ausgabe mit farbigen Statuszeilen (`[ OK ]`, `[WARN]`, `[FAIL]`, `[SKIP]`), ausgeführte Befehle grau.
- **Links:** Buttons
  - *Analyse*: alle Prüfungen, nur lesend (läuft beim Start automatisch)
  - *Fix*: repariert die Befunde der letzten Analyse
  - *Troubleshooting*: arbeitet den ganzen Aktionsbaum ab, prüft, repariert und testet nach
  - *Aktionsbaum*: zeigt Reihenfolge, Reparaturen und manuelle Hinweise
  - *WLAN-Bericht*: `netsh wlan show wlanreport` (HTML) erzeugen und öffnen
  - *Log-Ordner*, *Ausgabe leeren*, *Stopp*
  - Schalter „Tiefgreifende Reparaturen erlauben“ (standardmäßig aus)
- Statuszeile: Bereit/läuft, Admin ja/nein.

## Aktionsbaum (Reihenfolge)
| # | Prüfung | Automatische Reparatur | Manuell, wenn erfolglos |
|---|---|---|---|
| 1 | System/Modell (HP?) | – | – |
| 2 | HP-BIOS: WLAN aktiv, LAN/WLAN-Umschaltung | – | BIOS (F10) |
| 3 | WLAN-Adapter vorhanden | Hardware neu erkennen | Taste, BIOS, Treiber, Hardware-Service |
| 4 | Treiberzustand/-alter | Adapter neu starten, Gerät neu binden* | HP Support Assistant |
| 5 | Adapter aktiviert | Aktivieren | Netzwerkverbindungen |
| 6 | Funk/Flugmodus (Software & Hardware) | Funk einschalten, HP Wireless Button neu starten | Flugmodus-Taste F12/Fn+F12 |
| 7 | Dienste (WlanSvc, Dhcp, Dnscache, NlaSvc, netprofm) | Starten, WLAN-AutoConfig neu starten | services.msc |
| 8 | Energiesparen (Adapter + Energieplan) | Energiesparen abschalten | – |
| 9 | Verbindung | Adapter / WLAN-AutoConfig neu starten | Verbinden, Profil löschen |
| 10 | Signalstärke | – | Standort, Band, Antennen |
| 11 | IP-Konfiguration (APIPA, Gateway) | DHCP erneuern, Adapter neu, TCP/IP-Reset* | Router, DHCP-Tabelle |
| 12 | Router erreichbar | DHCP erneuern, Adapter neu | Router neu starten |
| 13 | Internet erreichbar | Adapter neu, Winsock-Reset* | Anbieter-Störung |
| 14 | DNS | Cache leeren, Adapter neu, manuelle DNS entfernen* | DNS im Router |
| 15 | Webzugriff / Captive Portal | – | Anmeldeseite |
| 16 | Proxy | Proxy zurücksetzen* | – |
| 17 | WLAN-Ereignisse 24 h | – | Treiber/Router-Firmware/Kanal |

\* tiefgreifend, nur mit Freigabe. Winsock- und TCP/IP-Reset brauchen einen Neustart.

Prüfungen mit Abhängigkeiten werden übersprungen, wenn ihre Voraussetzung fehlschlägt (ohne Funk keine IP-Prüfung).
Nach jeder Reparatur wird die Prüfung wiederholt; die nächste Reparatur kommt nur, wenn der Befund bleibt.

## Technik
- Python 3 mit Tkinter (Standardbibliothek), keine Fremdpakete zur Laufzeit.
- Abfragen per PowerShell (`Get-NetAdapter`, CIM/WMI, PnP, WinRT-Radio-API), `netsh`, `powercfg`, `ipconfig`, `pnputil`.
- netsh-Ausgaben werden auf deutschem und englischem Windows ausgewertet.
- HP-spezifisch: BIOS-Einstellungen über `root/HP/InstrumentedBIOS` (Business-Modelle), HP Wireless Button (HPQ6001).
- Reparaturen nur mit Adminrechten (UAC-Neustart per Button).
- Jede Sitzung schreibt ein Protokoll nach `%LOCALAPPDATA%\WLAN-Diagnose\logs`.
- Demo-Modus (`--demo`) simuliert ein defektes HP EliteBook, damit GUI und Baum ohne Windows testbar sind.
- Auslieferung als einzelne `WLAN-Diagnose.exe` per PyInstaller (`build.bat`), fordert Adminrechte an.

## Stand
- [x] Version 0.1: alle obigen Prüfungen und Reparaturen, GUI, Kommandozeile, Demo-Modus, Tests (Parser + Baum).
- [ ] Test auf echtem HP-Gerät (Windows 11, deutsch): PowerShell-Abfragen und Reparaturen verifizieren.
- [ ] Ideen danach: Treiber-Rollback, WLAN-Profile sichern/löschen, Kanal-Scan (`netsh wlan show networks mode=bssid`),
      Export eines Kurzberichts, HP-Treiber-Erkennung über HP Image Assistant (offline SoftPaq-Ordner).
