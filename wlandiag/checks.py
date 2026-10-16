"""Diagnose-Checks. Jeder Check liest nur und gibt ein Result zurück."""

from dataclasses import dataclass, field
from datetime import date

OK, INFO, WARN, FAIL, SKIP = "OK", "INFO", "WARN", "FAIL", "SKIP"
SEVERITY = {OK: 0, SKIP: 0, INFO: 1, WARN: 2, FAIL: 3}


@dataclass
class Result:
    status: str
    summary: str
    details: list = field(default_factory=list)
    # Optional: Reparaturen nur für diesen Befund (überschreibt die Liste im Aktionsbaum)
    fixes: list = None
    hint: str = None

    @property
    def bad(self):
        return self.status in (WARN, FAIL)


class Ctx:
    """Gemeinsamer Zustand eines Laufs: Abfragen, Aktionen und der gewählte Adapter."""

    def __init__(self, probe, actions, log):
        self.probe = probe
        self.actions = actions
        self.log = log
        self.adapter = None      # dict aus wifi_adapters()
        self.system = {}
        self.results = {}        # check-id -> Result
        self.static_dns = False

    @property
    def adapter_name(self):
        return self.adapter.get("Name") if self.adapter else None

    def refresh_adapter(self):
        """Adapterdaten neu lesen (nach einer Reparatur ändern sie sich)."""
        for a in self.probe.wifi_adapters():
            if a.get("Name") == self.adapter_name:
                self.adapter = a
        return self.adapter or {}

    @property
    def is_hp(self):
        m = (self.system.get("Manufacturer") or "").upper()
        return m.startswith("HP") or "HEWLETT" in m


def chk_system(ctx):
    s = ctx.probe.system_info()
    ctx.system = s
    if not s:
        return Result(WARN, "Systeminformationen nicht lesbar")
    det = [f"BIOS {s.get('Bios', '?')} ({s.get('BiosDate', '?')}), {s.get('Os', '')} Build {s.get('Build', '')}",
           f"Seriennummer {s.get('Serial', '?')}, Produktnr. {s.get('Sku', '?')}"]
    if not ctx.is_hp:
        return Result(INFO, f"{s.get('Manufacturer')} {s.get('Model')} (kein HP-Gerät, HP-Checks entfallen)", det)
    return Result(OK, s.get("Model", "HP"), det)


def chk_hp_bios(ctx):
    if not ctx.is_hp:
        return Result(SKIP, "kein HP-Gerät")
    rows = ctx.probe.hp_bios_wireless()
    if not rows:
        return Result(SKIP, "HP-BIOS-Abfrage nicht verfügbar (nur Business-Modelle)")
    det = [f"{r['Name']}: {r['Value']}" for r in rows]
    for r in rows:
        name, val = r["Name"].lower(), (r["Value"] or "").lower()
        if "wlan" in name and "switch" not in name and val.startswith("disable"):
            return Result(FAIL, "WLAN ist im BIOS deaktiviert", det,
                          hint="BIOS öffnen (F10 beim Start) > Advanced > Built-In Device Options > "
                               "Wireless Network Device (WLAN) aktivieren.")
    for r in rows:
        if "switch" in r["Name"].lower() and (r["Value"] or "").lower().startswith("enable"):
            return Result(WARN, "LAN/WLAN-Umschaltung aktiv: WLAN geht aus, sobald ein LAN-Kabel steckt", det,
                          hint="LAN-Kabel/Dockingstation trennen oder im BIOS 'LAN / WLAN Auto Switching' deaktivieren.")
    return Result(OK, "Funk im BIOS aktiviert", det)


def chk_adapter(ctx):
    adapters = ctx.probe.wifi_adapters()
    if not adapters:
        ctx.adapter = None
        problems = ctx.probe.problem_net_devices()
        det = [f"Gerät mit Fehler: {p.get('Name') or p.get('Id')} ({p.get('Status')})" for p in problems]
        return Result(FAIL, "Kein WLAN-Adapter erkannt", det)
    # Bevorzugt den Adapter, der gerade verbunden oder aktiv ist
    adapters.sort(key=lambda a: {"Up": 0, "Disconnected": 1}.get(a.get("Status"), 2))
    ctx.adapter = adapters[0]
    a = ctx.adapter
    det = [f"MAC {a.get('Mac')}, Status {a.get('Status')}"]
    if len(adapters) > 1:
        det.append("Weitere WLAN-Adapter: " + ", ".join(x.get("Name", "?") for x in adapters[1:]))
    return Result(OK, f"{a.get('Description')} ({a.get('Name')})", det)


def chk_driver(ctx):
    a = ctx.refresh_adapter()
    det = [f"Treiber {a.get('DriverVersion') or '?'} vom {a.get('DriverDate') or '?'} ({a.get('DriverProvider') or '?'})"]
    code = a.get("ProblemCode") or 0
    if code:
        return Result(FAIL, f"Gerätefehler Code {code} (Treiber defekt oder nicht gestartet)", det)
    try:
        y, m, d = (int(x) for x in a.get("DriverDate", "").split("-"))
        age = (date.today() - date(y, m, d)).days / 365.25
    except ValueError:
        age = None
    if age is not None and age > 3:
        return Result(WARN, f"Treiber ist {age:.0f} Jahre alt", det, fixes=[],
                      hint="Aktuellen WLAN-Treiber über HP Support Assistant oder hp.com/drivers installieren.")
    return Result(OK, "Treiber geladen", det)


def chk_enabled(ctx):
    if ctx.refresh_adapter().get("Status") == "Disabled":
        return Result(FAIL, "Adapter ist deaktiviert")
    return Result(OK, "Adapter ist aktiviert")


def chk_radio(ctx):
    radios = ctx.probe.radios()
    btn = ctx.probe.hp_wireless_button() if ctx.is_hp else []
    det = [f"{b.get('Name')}: {b.get('Status')}" for b in btn]
    if not radios:
        return Result(INFO, "Funkstatus nicht abfragbar", det)
    states = {r.get("State") for r in radios}
    if "On" in states:
        return Result(OK, "WLAN-Funk ist an", det)
    if "Disabled" in states:
        hint = ("Hardware-Funkschalter aus: Flugmodus-/WLAN-Taste drücken (meist F12 oder Fn+F12 "
                "mit Antennen-Symbol) und LED prüfen.")
        return Result(FAIL, "WLAN-Funk per Hardware-Schalter/Taste aus", det, fixes=["restart_hp_button"], hint=hint)
    return Result(FAIL, "WLAN-Funk aus (Flugmodus oder WLAN in Windows ausgeschaltet)", det)


def chk_services(ctx):
    svc = ctx.probe.services()
    det, bad = [], False
    for name in ("WlanSvc", "Dhcp", "Dnscache", "NlaSvc", "netprofm"):
        row = svc.get(name)
        if not row:
            det.append(f"{name}: nicht gefunden")
            bad |= name == "WlanSvc"
            continue
        det.append(f"{name}: {row.get('Status')} ({row.get('Start')})")
        if row.get("Status") != "Running" or (name in ("WlanSvc", "Dhcp") and row.get("Start") == "Disabled"):
            bad = True
    if bad:
        return Result(FAIL, "Netzwerkdienste laufen nicht vollständig", det)
    return Result(OK, "Netzwerkdienste laufen", det)


def chk_power(ctx):
    pm = ctx.probe.power_management(ctx.adapter_name)
    det, warn = [], []
    if pm.get("allow_off") == "Enabled":
        warn.append("Windows darf den Adapter zum Energiesparen abschalten")
    plan = pm.get("plan")
    if plan:
        names = {0: "Höchstleistung", 1: "Niedrig", 2: "Mittel", 3: "Maximal"}
        det.append(f"Energieplan WLAN-Sparmodus: Netz {names.get(plan['ac'], plan['ac'])}, "
                   f"Akku {names.get(plan['dc'], plan['dc'])}")
        if plan["ac"] >= 2 or plan["dc"] >= 2:
            warn.append("Energieplan drosselt den WLAN-Adapter")
    if warn:
        return Result(WARN, "; ".join(warn), det)
    return Result(OK, "Energiesparen beeinträchtigt WLAN nicht", det)


def chk_connection(ctx):
    info = ctx.probe.wlan_interface()
    if info.get("location_blocked"):
        names = [p.get("Name") for p in info.get("profiles", []) if p.get("Alias") == ctx.adapter_name]
        det = ["Windows 11 verlangt für WLAN-Details die Standortfreigabe (Einstellungen > Datenschutz > Standort)."]
        if names:
            return Result(OK, f"Verbunden mit {names[0]}", det)
        if ctx.refresh_adapter().get("Status") == "Up":
            return Result(OK, "Verbunden", det)
        return Result(FAIL, "Nicht mit einem WLAN verbunden", det)
    itfs = info.get("interfaces", [])
    itf = next((i for i in itfs if i.get("name") == ctx.adapter_name), itfs[0] if itfs else None)
    ctx.results["_wlan"] = itf
    if not itf or not itf.get("connected"):
        return Result(FAIL, "Nicht mit einem WLAN verbunden",
                      [f"Status: {itf.get('state')}"] if itf else [],
                      hint="Netz in der Taskleiste wählen und verbinden. Bei Passwortfehlern das Profil "
                           "löschen (netsh wlan delete profile name=\"<SSID>\") und neu verbinden.")
    det = [f"{itf.get('radio_type', '?')}, Kanal {itf.get('channel', '?')}, "
           f"Empfang {itf.get('rx', '?')} / Senden {itf.get('tx', '?')} Mbit/s",
           f"BSSID {itf.get('bssid', '?')}, Sicherheit {itf.get('auth', '?')}"]
    return Result(OK, f"Verbunden mit \"{itf.get('ssid')}\"", det)


def chk_signal(ctx):
    itf = ctx.results.get("_wlan")
    pct = itf.get("signal_pct") if itf else None
    if pct is None:
        return Result(SKIP, "Signalstärke nicht verfügbar")
    hint = ("Näher an den Router gehen, Hindernisse vermeiden, ggf. 2,4-GHz-Band oder Repeater/Mesh nutzen. "
            "Bleibt das Signal direkt am Router schwach: Antennenkabel/WLAN-Karte prüfen lassen.")
    if pct < 30:
        return Result(FAIL, f"Signal sehr schwach ({pct} %)", hint=hint)
    if pct < 55:
        return Result(WARN, f"Signal mäßig ({pct} %)", hint=hint)
    return Result(OK, f"Signal gut ({pct} %)")


def chk_ip(ctx):
    ip = ctx.probe.ip_config(ctx.adapter_name)
    ctx.results["_ip"] = ip
    ctx.static_dns = ctx.probe.static_dns(ctx.adapter_name)
    v4 = ip.get("IPv4") or []
    det = [f"IPv4 {', '.join(v4) or '-'}, Gateway {', '.join(ip.get('Gateway') or []) or '-'}, "
           f"DNS {', '.join(ip.get('Dns') or []) or '-'}, DHCP {ip.get('Dhcp', '?')}"]
    if not v4:
        return Result(FAIL, "Keine IPv4-Adresse", det)
    if all(a.startswith("169.254.") for a in v4):
        return Result(FAIL, "Keine Adresse vom Router erhalten (APIPA 169.254.x.x)", det)
    if not ip.get("Gateway"):
        return Result(FAIL, "Kein Standardgateway", det)
    return Result(OK, f"IP {v4[0]}", det)


def chk_gateway(ctx):
    gw = (ctx.results.get("_ip") or {}).get("Gateway") or []
    if not gw:
        return Result(SKIP, "kein Gateway")
    p = ctx.probe.ping(gw[0])
    hint = "Router neu starten (30 s vom Strom trennen)."
    if p["ok"] == 0:
        return Result(FAIL, f"Router {gw[0]} antwortet nicht", hint=hint)
    if p["ok"] < p["sent"]:
        return Result(WARN, f"Paketverlust zum Router ({p['sent'] - p['ok']}/{p['sent']}), {p['ms']} ms", hint=hint)
    return Result(OK, f"Router {gw[0]} erreichbar ({p['ms']} ms)")


def chk_internet(ctx):
    for host in ("1.1.1.1", "8.8.8.8"):
        p = ctx.probe.ping(host)
        if p["ok"]:
            if p["ms"] and p["ms"] > 150:
                return Result(WARN, f"Internet langsam ({host}: {p['ms']} ms)")
            return Result(OK, f"Internet erreichbar ({host}: {p['ms']} ms)")
    return Result(FAIL, "Internet nicht erreichbar (Ping 1.1.1.1 / 8.8.8.8)",
                  hint="Router-Internetverbindung prüfen (Info-LED) oder Störung beim Anbieter.")


def chk_dns(ctx):
    r = ctx.probe.dns_resolve("www.msftconnecttest.com")
    if r.get("Ip"):
        return Result(OK, "Namensauflösung funktioniert")
    fixes = ["flush_dns", "restart_adapter"] + (["reset_dns_to_dhcp"] if ctx.static_dns else [])
    det = [r.get("Err") or ""] + (["Manuell eingetragene DNS-Server gefunden"] if ctx.static_dns else [])
    return Result(FAIL, "DNS-Auflösung schlägt fehl", [d for d in det if d], fixes=fixes)


def chk_http(ctx):
    h = ctx.probe.http_check()
    if h.get("reachable") and h.get("expected"):
        return Result(OK, "Webzugriff funktioniert")
    if h.get("reachable"):
        return Result(WARN, "Anmeldeseite (Captive Portal) erkannt", [f"Umgeleitet auf {h.get('final_url')}"],
                      hint="Browser öffnen und im Hotel/Gäste-WLAN anmelden.")
    return Result(FAIL, "Webzugriff fehlgeschlagen", [h.get("error", "")])


def chk_proxy(ctx):
    p = ctx.probe.proxy()
    det = []
    if p.get("user_enabled"):
        det.append(f"Benutzer-Proxy: {p.get('user_server')}")
    if p.get("pac"):
        det.append(f"PAC-Skript: {p.get('pac')}")
    if not p.get("winhttp_direct"):
        det.append("WinHTTP-Proxy gesetzt")
    if not det:
        return Result(OK, "Kein Proxy")
    http = ctx.results.get("http")
    if http and http.status == FAIL:
        return Result(WARN, "Proxy eingetragen und Webzugriff gestört", det)
    return Result(INFO, "Proxy eingetragen (Webzugriff funktioniert)", det)


def chk_events(ctx):
    ev = ctx.probe.wlan_events(24)
    if not ev:
        return Result(OK, "Keine WLAN-Fehler in den letzten 24 h")
    fails = [e for e in ev if e.get("Id") in (8002, 11006, 12013)]
    drops = [e for e in ev if e.get("Id") == 8003]
    det = [f"{e['Time']}  {e['Id']}  {e['Msg']}" for e in ev[:5]]
    summary = f"{len(ev)} Warnungen/Fehler in 24 h ({len(fails)} Verbindungsfehler, {len(drops)} Abbrüche)"
    if len(ev) >= 5:
        return Result(WARN, summary, det,
                      hint="Häufige Abbrüche: WLAN-Treiber aktualisieren, Router-Firmware prüfen, "
                           "anderen Funkkanal im Router testen.")
    return Result(INFO, summary, det)
