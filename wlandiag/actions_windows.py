"""Reparaturaktionen auf Windows. Jede Methode gibt (ok, meldung) zurück."""

import os
import time

from .probe_windows import POWERCFG_SETTING, POWERCFG_SUB, RADIO_ON
from .runner import Runner, ps_quote

WLAN_REPORT = r"C:\ProgramData\Microsoft\Windows\WlanReport\wlan-report-latest.html"


class WindowsActions:
    def __init__(self, runner: Runner):
        self.r = runner

    def _out(self, res, show_lines=6):
        for line in (res.out + res.err).strip().splitlines()[:show_lines]:
            if line.strip():
                self.r.log("  " + line.rstrip(), "dim")
        return res

    def _ps(self, script, label, timeout=90):
        self.r.log("> " + label, "cmd")
        res = self._out(self.r.ps(script, timeout=timeout))
        return res.ok, ("ok" if res.ok else (res.err.strip().splitlines() or ["Fehler"])[-1])

    def enable_adapter(self, adapter):
        return self._ps(f"Enable-NetAdapter -Name {ps_quote(adapter)} -Confirm:$false",
                        f"Enable-NetAdapter {adapter}")

    def restart_adapter(self, adapter):
        ok, msg = self._ps(f"Restart-NetAdapter -Name {ps_quote(adapter)} -Confirm:$false",
                           f"Restart-NetAdapter {adapter}")
        time.sleep(8)  # Zeit zum Wiederverbinden
        return ok, msg

    def radio_on(self, adapter=None):
        return self._ps(RADIO_ON, "WLAN-Funk einschalten (Flugmodus/Software-Schalter)")

    def restart_hp_button(self, adapter=None):
        return self._ps(r"""
$d = Get-PnpDevice | Where-Object { $_.FriendlyName -match 'Wireless Button' -or $_.InstanceId -match 'HPQ6001' } | Select-Object -First 1
if (-not $d) { throw 'HP Wireless Button nicht gefunden' }
Disable-PnpDevice -InstanceId $d.InstanceId -Confirm:$false; Start-Sleep 2
Enable-PnpDevice -InstanceId $d.InstanceId -Confirm:$false
""", "HP Wireless Button Treiber neu starten")

    def disable_power_saving(self, adapter):
        ok1, msg = self._ps(
            f"Set-NetAdapterPowerManagement -Name {ps_quote(adapter)} -AllowComputerToTurnOffDevice Disabled",
            "Energiesparen für den Adapter abschalten")
        ok2 = True
        for flag in ("/setacvalueindex", "/setdcvalueindex"):
            ok2 &= self._out(self.r.run(["powercfg", flag, "SCHEME_CURRENT", POWERCFG_SUB,
                                         POWERCFG_SETTING, "0"])).ok
        ok2 &= self._out(self.r.run(["powercfg", "/setactive", "SCHEME_CURRENT"])).ok
        return ok1 and ok2, msg if not ok1 else ("ok" if ok2 else "Energieplan nicht änderbar")

    def start_services(self, adapter=None):
        return self._ps(r"""
foreach ($n in 'WlanSvc','Dhcp') { Set-Service -Name $n -StartupType Automatic }
foreach ($n in 'Dhcp','Dnscache','NlaSvc','netprofm','WlanSvc') {
  $s = Get-Service $n -ErrorAction SilentlyContinue
  if ($s -and $s.Status -ne 'Running') { Start-Service $n; Write-Output "$n gestartet" } }
""", "Netzwerkdienste starten")

    def restart_wlansvc(self, adapter=None):
        ok, msg = self._ps("Restart-Service WlanSvc -Force", "WLAN-AutoConfig neu starten")
        time.sleep(5)
        return ok, msg

    def renew_ip(self, adapter):
        self._out(self.r.run(["ipconfig", "/release", adapter], timeout=60))
        res = self._out(self.r.run(["ipconfig", "/renew", adapter], timeout=90))
        return res.ok, "ok" if res.ok else "DHCP antwortet nicht"

    def flush_dns(self, adapter=None):
        res = self._out(self.r.run(["ipconfig", "/flushdns"]))
        return res.ok, "ok" if res.ok else "fehlgeschlagen"

    def reset_dns_to_dhcp(self, adapter):
        return self._ps(f"Set-DnsClientServerAddress -InterfaceAlias {ps_quote(adapter)} -ResetServerAddresses",
                        "DNS-Server auf automatisch (DHCP) zurücksetzen")

    def reset_proxy(self, adapter=None):
        res = self._out(self.r.run(["netsh", "winhttp", "reset", "proxy"]))
        ok, _ = self._ps(r"Set-ItemProperty 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings' "
                         "-Name ProxyEnable -Value 0", "Benutzer-Proxy deaktivieren")
        return res.ok and ok, "ok"

    def reset_winsock(self, adapter=None):
        res = self._out(self.r.run(["netsh", "winsock", "reset"]))
        return res.ok, "Neustart erforderlich" if res.ok else "fehlgeschlagen"

    def reset_tcpip(self, adapter=None):
        res = self._out(self.r.run(["netsh", "int", "ip", "reset"]))
        return res.ok, "Neustart erforderlich" if res.ok else "fehlgeschlagen"

    def rescan_devices(self, adapter=None):
        res = self._out(self.r.run(["pnputil", "/scan-devices"], timeout=120))
        time.sleep(5)
        return res.ok, "ok" if res.ok else "fehlgeschlagen"

    def reinstall_driver(self, adapter, pnp_id=None):
        if not pnp_id:
            return False, "Geräte-ID unbekannt"
        # Entfernt nur das Gerät; das Treiberpaket bleibt im Store und wird beim Scan neu gebunden.
        self._out(self.r.run(["pnputil", "/remove-device", pnp_id], timeout=120))
        res = self._out(self.r.run(["pnputil", "/scan-devices"], timeout=180))
        time.sleep(10)
        return res.ok, "ok" if res.ok else "fehlgeschlagen"

    def wlan_report(self, adapter=None):
        res = self._out(self.r.run(["netsh", "wlan", "show", "wlanreport"], timeout=180), show_lines=3)
        if os.path.exists(WLAN_REPORT):
            return True, WLAN_REPORT
        return res.ok, "Bericht nicht gefunden"
