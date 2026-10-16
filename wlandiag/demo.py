"""Simuliertes HP-Notebook mit WLAN-Problemen, damit sich Oberfläche und
Aktionsbaum ohne Windows vorführen und testen lassen (Start mit --demo)."""

import time


class SimState:
    def __init__(self):
        self.adapter_enabled = True
        self.radio = "Off"              # Flugmodus aktiv
        self.allow_off = "Enabled"      # Energiesparen am Adapter
        self.plan_dc = 3                # Energieplan: maximale Energieeinsparung im Akkubetrieb
        self.wlansvc = "Running"
        self.apipa = True               # 169.254.x.x ohne DHCP
        self.dns_cache_broken = True
        self.delay = 0.15


class DemoProbe:
    def __init__(self, runner, state=None):
        self.r = runner
        self.s = state or SimState()

    def _cmd(self, label):
        self.r.log("> " + label, "cmd")
        time.sleep(self.s.delay)

    def _connected(self):
        return self.s.adapter_enabled and self.s.radio == "On" and self.s.wlansvc == "Running"

    def system_info(self):
        self._cmd("PowerShell: Systeminformationen")
        return {"Manufacturer": "HP", "Model": "HP EliteBook 840 G8 Notebook PC", "Bios": "T37 Ver. 01.12.00",
                "BiosDate": "2023-02-14", "Os": "Microsoft Windows 11 Pro", "Build": "22631",
                "Serial": "5CG1234DEM", "Sku": "3C6G2EA#ABD"}

    def hp_bios_wireless(self):
        self._cmd("PowerShell: HP-BIOS (Funk)")
        return [{"Name": "Wireless Network Device (WLAN)", "Value": "Enable"},
                {"Name": "LAN / WLAN Auto Switching", "Value": "Disable"}]

    def wifi_adapters(self):
        self._cmd("PowerShell: WLAN-Adapter")
        status = ("Up" if self._connected() else "Disconnected") if self.s.adapter_enabled else "Disabled"
        return [{"Name": "WLAN", "Description": "Intel(R) Wi-Fi 6 AX201 160MHz", "Status": status,
                 "Mac": "A4-B1-C1-12-34-56", "PnpId": "PCI\\VEN_8086&DEV_A0F0&SUBSYS_00748086\\3&11583659&0&A3",
                 "DriverVersion": "22.110.1.1", "DriverDate": "2022-01-18", "DriverProvider": "Intel",
                 "ProblemCode": 0}]

    def problem_net_devices(self):
        self._cmd("PowerShell: Geräte mit Fehlern")
        return []

    def hp_wireless_button(self):
        self._cmd("PowerShell: HP Wireless Button")
        return [{"Name": "HP Wireless Button Driver", "Status": "OK", "Id": "ACPI\\HPQ6001\\0"}]

    def radios(self):
        self._cmd("PowerShell: Funkstatus (WinRT)")
        return [{"Name": "WLAN", "State": self.s.radio}]

    def power_management(self, adapter):
        self._cmd("PowerShell: Energieverwaltung Adapter")
        return {"allow_off": self.s.allow_off, "plan": {"ac": 0, "dc": self.s.plan_dc}}

    def services(self):
        self._cmd("PowerShell: Dienste")
        rows = {n: {"Name": n, "Status": "Running", "Start": "Automatic"}
                for n in ("WlanSvc", "Dhcp", "Dnscache", "NlaSvc", "netprofm")}
        rows["WlanSvc"]["Status"] = self.s.wlansvc
        return rows

    def wlan_interface(self):
        self._cmd("netsh wlan show interfaces")
        if not self._connected():
            return {"interfaces": [{"name": "WLAN", "state": "getrennt", "connected": False, "signal_pct": None}]}
        return {"interfaces": [{"name": "WLAN", "state": "verbunden", "connected": True, "ssid": "FRITZ!Box 7590 XY",
                                "bssid": "3c:a6:2f:11:22:33", "radio_type": "802.11ax", "channel": "36",
                                "rx": "1201", "tx": "960", "signal": "78%", "signal_pct": 78, "auth": "WPA3-Personal"}]}

    def ip_config(self, adapter):
        self._cmd("PowerShell: IP-Konfiguration")
        if not self._connected():
            return {"IPv4": [], "Gateway": [], "Dns": [], "Dhcp": "Enabled"}
        if self.s.apipa:
            return {"IPv4": ["169.254.83.17"], "Gateway": [], "Dns": [], "Dhcp": "Enabled"}
        return {"IPv4": ["192.168.178.42"], "Gateway": ["192.168.178.1"], "Dns": ["192.168.178.1"], "Dhcp": "Enabled"}

    def static_dns(self, adapter):
        return False

    def ping(self, host, timeout_ms=1500):
        self._cmd(f"Ping {host}")
        ok = self._connected() and not self.s.apipa
        return {"ok": 3 if ok else 0, "ms": (3 if host.startswith("192.") else 18) if ok else None, "sent": 3}

    def dns_resolve(self, name):
        self._cmd(f"DNS {name}")
        if self._connected() and not self.s.apipa and not self.s.dns_cache_broken:
            return {"Ip": "23.53.120.98"}
        return {"Ip": None, "Err": "DNS name does not exist"}

    def http_check(self):
        self._cmd("HTTP http://www.msftconnecttest.com/connecttest.txt")
        ok = self._connected() and not self.s.apipa and not self.s.dns_cache_broken
        return {"reachable": ok, "expected": ok} if ok else {"reachable": False, "error": "getaddrinfo failed"}

    def proxy(self):
        self._cmd("netsh winhttp show proxy")
        return {"winhttp_direct": True, "user_enabled": False, "user_server": None, "pac": None}

    def wlan_events(self, hours=24):
        self._cmd("PowerShell: Ereignisprotokoll WLAN-AutoConfig")
        return [{"Time": "2026-10-15 22:1%d" % i, "Id": 8002, "Level": 2,
                 "Msg": "Fehler bei der WLAN-Verbindung."} for i in range(4)] + [
                {"Time": "2026-10-15 23:05", "Id": 8003, "Level": 3, "Msg": "Die WLAN-Verbindung wurde getrennt."}]


class DemoActions:
    def __init__(self, runner, state):
        self.r = runner
        self.s = state

    def _do(self, label):
        self.r.log("> " + label, "cmd")
        time.sleep(self.s.delay * 3)

    def enable_adapter(self, adapter):
        self._do(f"Enable-NetAdapter {adapter}")
        self.s.adapter_enabled = True
        return True, "ok"

    def restart_adapter(self, adapter):
        self._do(f"Restart-NetAdapter {adapter}")
        return True, "ok"

    def radio_on(self, adapter=None):
        self._do("WLAN-Funk einschalten (Flugmodus/Software-Schalter)")
        self.s.radio = "On"
        return True, "ok"

    def restart_hp_button(self, adapter=None):
        self._do("HP Wireless Button Treiber neu starten")
        return True, "ok"

    def disable_power_saving(self, adapter):
        self._do("Energiesparen für den Adapter abschalten")
        self.s.allow_off, self.s.plan_dc = "Disabled", 0
        return True, "ok"

    def start_services(self, adapter=None):
        self._do("Netzwerkdienste starten")
        self.s.wlansvc = "Running"
        return True, "ok"

    def restart_wlansvc(self, adapter=None):
        self._do("WLAN-AutoConfig neu starten")
        return True, "ok"

    def renew_ip(self, adapter):
        self._do(f"ipconfig /release + /renew {adapter}")
        self.s.apipa = False
        return True, "ok"

    def flush_dns(self, adapter=None):
        self._do("ipconfig /flushdns")
        self.s.dns_cache_broken = False
        return True, "ok"

    def reset_dns_to_dhcp(self, adapter):
        self._do("DNS-Server auf automatisch (DHCP) zurücksetzen")
        return True, "ok"

    def reset_proxy(self, adapter=None):
        self._do("netsh winhttp reset proxy")
        return True, "ok"

    def reset_winsock(self, adapter=None):
        self._do("netsh winsock reset")
        return True, "Neustart erforderlich"

    def reset_tcpip(self, adapter=None):
        self._do("netsh int ip reset")
        return True, "Neustart erforderlich"

    def rescan_devices(self, adapter=None):
        self._do("pnputil /scan-devices")
        return True, "ok"

    def reinstall_driver(self, adapter, pnp_id=None):
        self._do("pnputil /remove-device + /scan-devices")
        return True, "ok"

    def wlan_report(self, adapter=None):
        self._do("netsh wlan show wlanreport")
        return False, "Im Demo-Modus nicht verfügbar"
