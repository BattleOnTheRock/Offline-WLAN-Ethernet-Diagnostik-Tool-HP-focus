"""Offline-Aktionsbaum: Reihenfolge der Checks, Reparaturen je Befund und
manuelle Hinweise, wenn keine automatische Reparatur greift."""

from dataclasses import dataclass, field

from . import checks as C


@dataclass
class Fix:
    id: str
    title: str
    invasive: bool = False   # nur mit Freigabe "tiefgreifende Reparaturen"
    reboot: bool = False     # wirkt erst nach Neustart, daher kein Nachtest


FIXES = {f.id: f for f in [
    Fix("rescan_devices", "Hardware neu erkennen (pnputil /scan-devices)"),
    Fix("enable_adapter", "WLAN-Adapter aktivieren"),
    Fix("radio_on", "WLAN-Funk einschalten / Flugmodus aus"),
    Fix("restart_hp_button", "HP Wireless Button Treiber neu starten"),
    Fix("start_services", "Netzwerkdienste starten und auf Automatisch setzen"),
    Fix("restart_wlansvc", "Dienst WLAN-AutoConfig neu starten"),
    Fix("disable_power_saving", "Energiesparen für WLAN abschalten"),
    Fix("restart_adapter", "WLAN-Adapter neu starten"),
    Fix("renew_ip", "IP-Adresse neu anfordern (DHCP)"),
    Fix("flush_dns", "DNS-Cache leeren"),
    Fix("reset_dns_to_dhcp", "Manuelle DNS-Server entfernen (DHCP)", invasive=True),
    Fix("reset_proxy", "Proxy-Einstellungen zurücksetzen", invasive=True),
    Fix("reinstall_driver", "WLAN-Gerät entfernen und Treiber neu binden", invasive=True),
    Fix("reset_winsock", "Winsock zurücksetzen", invasive=True, reboot=True),
    Fix("reset_tcpip", "TCP/IP-Stack zurücksetzen", invasive=True, reboot=True),
]}


@dataclass
class Node:
    id: str
    title: str
    check: object
    fixes: list = field(default_factory=list)
    hint: str = None          # manueller Schritt, wenn alles Automatische versagt
    requires: list = field(default_factory=list)
    stop: bool = False        # Fehler hier blockiert alle Prüfungen, die davon abhängen (requires)


ADAPTER_HINT = ("1) Flugmodus-/WLAN-Taste prüfen. 2) BIOS (F10): WLAN aktiviert? 3) WLAN-Treiber über "
                "HP Support Assistant bzw. hp.com/drivers installieren. 4) Bleibt der Adapter unsichtbar: "
                "WLAN-Karte oder Antennen defekt, Hardware-Service nötig.")

TREE = [
    Node("system", "System / Modell", C.chk_system),
    Node("hp_bios", "HP-BIOS Funkeinstellungen", C.chk_hp_bios),
    Node("adapter", "WLAN-Adapter vorhanden", C.chk_adapter, ["rescan_devices"], ADAPTER_HINT, stop=True),
    Node("driver", "Treiberzustand", C.chk_driver, ["restart_adapter", "reinstall_driver"],
         "Treiber über HP Support Assistant oder hp.com/drivers neu installieren.", ["adapter"]),
    Node("enabled", "Adapter aktiviert", C.chk_enabled, ["enable_adapter"],
         "Systemsteuerung > Netzwerkverbindungen > WLAN > Aktivieren.", ["adapter"], stop=True),
    Node("radio", "Funk / Flugmodus", C.chk_radio, ["radio_on", "restart_hp_button"],
         "Flugmodus in der Taskleiste ausschalten und WLAN-Taste (F12 / Fn+F12) drücken.", ["adapter"], stop=True),
    Node("services", "Netzwerkdienste", C.chk_services, ["start_services", "restart_wlansvc"],
         "Dienste-Konsole (services.msc): WLAN-AutoConfig auf Automatisch und starten.", stop=True),
    Node("power", "Energiesparoptionen", C.chk_power, ["disable_power_saving"], requires=["adapter"]),
    Node("connection", "WLAN-Verbindung", C.chk_connection, ["restart_adapter", "restart_wlansvc"],
         requires=["adapter", "radio", "services"], stop=True),
    Node("signal", "Signalstärke", C.chk_signal, requires=["connection"]),
    Node("ip", "IP-Konfiguration", C.chk_ip, ["renew_ip", "restart_adapter", "reset_tcpip"],
         "Router neu starten; prüfen, ob am Router MAC-Filter oder volle DHCP-Tabelle aktiv sind.",
         ["connection"], stop=True),
    Node("gateway", "Router erreichbar", C.chk_gateway, ["renew_ip", "restart_adapter"], requires=["ip"]),
    Node("internet", "Internet erreichbar", C.chk_internet, ["restart_adapter", "reset_winsock"], requires=["ip"]),
    Node("dns", "Namensauflösung (DNS)", C.chk_dns, ["flush_dns", "restart_adapter"],
         "Im Router DNS-Server prüfen oder testweise 1.1.1.1 eintragen.", ["ip"]),
    Node("http", "Webzugriff", C.chk_http, [], requires=["ip"]),
    Node("proxy", "Proxy", C.chk_proxy, ["reset_proxy"]),
    Node("events", "WLAN-Ereignisse (24 h)", C.chk_events),
]

NODES = {n.id: n for n in TREE}


def describe_tree():
    """Aktionsbaum als Textzeilen (für die Anzeige im Terminalfenster)."""
    lines = []
    for i, n in enumerate(TREE, 1):
        req = f"  [braucht: {', '.join(n.requires)}]" if n.requires else ""
        lines.append((f"{i:2}. {n.title}{req}", "head"))
        for f in n.fixes:
            fx = FIXES[f]
            flags = "".join([" (tiefgreifend)" if fx.invasive else "", " (Neustart)" if fx.reboot else ""])
            lines.append((f"      ├─ Fix: {fx.title}{flags}", "fix"))
        if n.hint:
            lines.append((f"      └─ Manuell: {n.hint}", "dim"))
        if n.stop:
            lines.append(("      └─ bei Fehler: Abbruch der Folgeprüfungen", "dim"))
    return lines
