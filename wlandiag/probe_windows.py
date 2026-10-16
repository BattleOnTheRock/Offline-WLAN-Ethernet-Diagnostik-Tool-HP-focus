"""Lesende Abfragen auf Windows 10/11. Jede Methode liefert einfache Python-Daten.

Alle Abfragen funktionieren offline. netsh-Ausgaben werden für deutsches und
englisches Windows ausgewertet.
"""

import re
import urllib.request

from .runner import Runner, ps_quote

# netsh-Schlüssel (Englisch / Deutsch) auf einheitliche Namen abbilden.
_NETSH_KEYS = {
    "name": "name",
    "description": "description", "beschreibung": "description",
    "state": "state", "status": "state",
    "ssid": "ssid",
    "bssid": "bssid", "ap bssid": "bssid",
    "radio type": "radio_type", "funktyp": "radio_type",
    "band": "band",
    "channel": "channel", "kanal": "channel",
    "receive rate (mbps)": "rx", "empfangsrate (mbit/s)": "rx",
    "transmit rate (mbps)": "tx", "übertragungsrate (mbit/s)": "tx",
    "signal": "signal",
    "profile": "profile", "profil": "profile",
    "authentication": "auth", "authentifizierung": "auth",
}

_CONNECTED_WORDS = ("connected", "verbunden")
_DISCONNECTED_WORDS = ("disconnected", "getrennt", "nicht verbunden")

# WinRT-Radio-API: Flugmodus / Software-Schalter lesen und setzen.
_RADIO_PS = r"""
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$asTask = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
  $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and
  $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
function Await($op, $type) {
  $t = $asTask.MakeGenericMethod($type).Invoke($null, @($op)); $t.Wait(-1) | Out-Null; $t.Result }
[Windows.Devices.Radios.Radio,Windows.System.Devices,ContentType=WindowsRuntime] | Out-Null
"""

_RADIO_LIST = _RADIO_PS + r"""
$radios = Await ([Windows.Devices.Radios.Radio]::GetRadiosAsync()) ([System.Collections.Generic.IReadOnlyList[Windows.Devices.Radios.Radio]])
@($radios | Where-Object { [string]$_.Kind -eq 'WiFi' } | ForEach-Object {
  [pscustomobject]@{ Name = $_.Name; State = [string]$_.State } }) | ConvertTo-Json
"""

RADIO_ON = _RADIO_PS + r"""
Await ([Windows.Devices.Radios.Radio]::RequestAccessAsync()) ([Windows.Devices.Radios.RadioAccessStatus]) | Out-Null
$radios = Await ([Windows.Devices.Radios.Radio]::GetRadiosAsync()) ([System.Collections.Generic.IReadOnlyList[Windows.Devices.Radios.Radio]])
foreach ($r in $radios) { if ([string]$r.Kind -eq 'WiFi') {
  $s = Await ($r.SetStateAsync('On')) ([Windows.Devices.Radios.RadioAccessStatus]); Write-Output ("$($r.Name): $s") } }
"""

# Energieoptionen > Drahtlosadapter > Energiesparmodus
POWERCFG_SUB = "19cbb8fa-5279-450e-9fac-8a3d5fedd0c1"
POWERCFG_SETTING = "12bbebe6-58d6-4636-95bb-3217ef867c1a"


def parse_netsh_interfaces(text):
    """`netsh wlan show interfaces` in eine Liste von Dicts zerlegen."""
    interfaces, cur = [], None
    for line in text.splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip().lower()
        value = value.strip()
        field = _NETSH_KEYS.get(key)
        if field is None:
            continue
        if field == "name":
            cur = {"name": value}
            interfaces.append(cur)
        elif cur is not None and field not in cur:
            cur[field] = value
    for itf in interfaces:
        state = itf.get("state", "").lower()
        itf["connected"] = state in _CONNECTED_WORDS or (
            any(w in state for w in _CONNECTED_WORDS)
            and not any(w in state for w in _DISCONNECTED_WORDS))
        m = re.search(r"(\d+)\s*%", itf.get("signal", ""))
        itf["signal_pct"] = int(m.group(1)) if m else None
    return interfaces


def parse_powercfg_indices(text):
    """Aus `powercfg /qh` die aktuellen AC/DC-Indizes lesen (sprachunabhängig)."""
    vals = re.findall(r"0x([0-9a-fA-F]{8})", text)
    if len(vals) < 2:
        return None
    return {"ac": int(vals[-2], 16), "dc": int(vals[-1], 16)}


class WindowsProbe:
    def __init__(self, runner: Runner):
        self.r = runner

    # --- System ---------------------------------------------------------
    def system_info(self):
        data = self.r.ps_json(r"""
$cs = Get-CimInstance Win32_ComputerSystem; $b = Get-CimInstance Win32_BIOS
$os = Get-CimInstance Win32_OperatingSystem
$p = Get-CimInstance Win32_ComputerSystemProduct
[pscustomobject]@{ Manufacturer=$cs.Manufacturer; Model=$cs.Model; Bios=$b.SMBIOSBIOSVersion;
  BiosDate=if($b.ReleaseDate){$b.ReleaseDate.ToString('yyyy-MM-dd')}; Serial=$b.SerialNumber;
  Sku=$cs.SystemSKUNumber; Os=$os.Caption; Build=$os.BuildNumber; Product=$p.Version } | ConvertTo-Json
""", label="Systeminformationen")
        return data[0] if data else {}

    def hp_bios_wireless(self):
        """Funk-relevante BIOS-Einstellungen (nur HP Business-Geräte mit HP-WMI)."""
        return self.r.ps_json(r"""
try { @(Get-CimInstance -Namespace root/HP/InstrumentedBIOS -ClassName HP_BIOSEnumeration -ErrorAction Stop |
  Where-Object { $_.Name -match 'WLAN|Wireless|LAN.*Switch|Radio' } |
  ForEach-Object { [pscustomobject]@{ Name=$_.Name; Value=[string]$_.CurrentValue } }) | ConvertTo-Json }
catch { '[]' }
""", label="HP-BIOS (Funk)")

    # --- Adapter / Treiber ------------------------------------------------
    def wifi_adapters(self):
        return self.r.ps_json(r"""
@(Get-NetAdapter -Physical -ErrorAction SilentlyContinue | Where-Object {
    $_.PhysicalMediaType -match '802\.11' -or $_.NdisPhysicalMedium -eq 9 -or
    $_.InterfaceDescription -match 'Wi-?Fi|Wireless|WLAN|802\.11' } | ForEach-Object {
  $id = $_.PnPDeviceID
  $d = Get-CimInstance Win32_PnPSignedDriver -Filter ("DeviceID='" + ($id -replace '\\','\\') + "'") -ErrorAction SilentlyContinue
  $pc = (Get-PnpDeviceProperty -InstanceId $id -KeyName DEVPKEY_Device_ProblemCode -ErrorAction SilentlyContinue).Data
  [pscustomobject]@{ Name=$_.Name; Description=$_.InterfaceDescription; Status=[string]$_.Status;
    Mac=$_.MacAddress; PnpId=$id; DriverVersion=$d.DriverVersion;
    DriverDate=if($d.DriverDate){$d.DriverDate.ToString('yyyy-MM-dd')}; DriverProvider=$d.DriverProviderName;
    ProblemCode=$pc } }) | ConvertTo-Json
""", label="WLAN-Adapter")

    def problem_net_devices(self):
        """Netzwerk- oder unbekannte Geräte mit Fehlerstatus (z. B. fehlender Treiber)."""
        return self.r.ps_json(r"""
@(Get-PnpDevice -PresentOnly -ErrorAction SilentlyContinue | Where-Object {
    $_.Status -ne 'OK' -and ($_.Class -eq 'Net' -or -not $_.Class -or $_.FriendlyName -match 'Network|Netzwerk|Wireless|Wi-?Fi|WLAN') } |
  ForEach-Object { [pscustomobject]@{ Name=$_.FriendlyName; Class=$_.Class; Status=[string]$_.Status; Id=$_.InstanceId } }) | ConvertTo-Json
""", label="Geräte mit Fehlern")

    def hp_wireless_button(self):
        data = self.r.ps_json(r"""
@(Get-PnpDevice -ErrorAction SilentlyContinue | Where-Object {
    $_.FriendlyName -match 'Wireless Button|Funktaste|Airplane Mode' -or $_.InstanceId -match 'HPQ6001' } |
  ForEach-Object { [pscustomobject]@{ Name=$_.FriendlyName; Status=[string]$_.Status; Id=$_.InstanceId } }) | ConvertTo-Json
""", label="HP Wireless Button")
        return data

    def radios(self):
        """WLAN-Funk: State On / Off (Software/Flugmodus) / Disabled (Hardware-Schalter)."""
        return self.r.ps_json(_RADIO_LIST, label="Funkstatus (WinRT)")

    def power_management(self, adapter):
        data = self.r.ps_json(
            f"@(Get-NetAdapterPowerManagement -Name {ps_quote(adapter)} | ForEach-Object {{"
            " [pscustomobject]@{ AllowOff=[string]$_.AllowComputerToTurnOffDevice } }) | ConvertTo-Json",
            label="Energieverwaltung Adapter")
        allow_off = data[0].get("AllowOff") if data else None
        r = self.r.run(["powercfg", "/qh", "SCHEME_CURRENT", POWERCFG_SUB, POWERCFG_SETTING], echo=False)
        plan = parse_powercfg_indices(r.out) if r.ok else None
        return {"allow_off": allow_off, "plan": plan}

    # --- Dienste ----------------------------------------------------------
    def services(self):
        rows = self.r.ps_json(
            "@(Get-Service WlanSvc,Dhcp,Dnscache,NlaSvc,netprofm -ErrorAction SilentlyContinue |"
            " ForEach-Object { [pscustomobject]@{ Name=$_.Name; Status=[string]$_.Status; Start=[string]$_.StartType } })"
            " | ConvertTo-Json", label="Dienste")
        return {row["Name"]: row for row in rows}

    # --- Verbindung -------------------------------------------------------
    def wlan_interface(self):
        r = self.r.run(["netsh", "wlan", "show", "interfaces"], echo=False)
        text = (r.out or "") + (r.err or "")
        low = text.lower()
        if "location" in low or "standort" in low:
            # Windows 11 24H2: netsh braucht die Standortberechtigung für SSID/BSSID.
            info = {"location_blocked": True}
            prof = self.r.ps_json(
                "@(Get-NetConnectionProfile -ErrorAction SilentlyContinue | ForEach-Object {"
                " [pscustomobject]@{ Name=$_.Name; Alias=$_.InterfaceAlias }}) | ConvertTo-Json")
            info["profiles"] = prof
            return info
        itfs = parse_netsh_interfaces(text)
        return {"interfaces": itfs, "raw_ok": r.ok}

    def ip_config(self, adapter):
        a = ps_quote(adapter)
        data = self.r.ps_json(f"""
$c = Get-NetIPConfiguration -InterfaceAlias {a} -ErrorAction SilentlyContinue
$i = Get-NetIPInterface -InterfaceAlias {a} -AddressFamily IPv4 -ErrorAction SilentlyContinue
$dns = Get-DnsClientServerAddress -InterfaceAlias {a} -AddressFamily IPv4 -ErrorAction SilentlyContinue
[pscustomobject]@{{ IPv4=@($c.IPv4Address | ForEach-Object {{ $_.IPAddress }});
  Gateway=@($c.IPv4DefaultGateway | ForEach-Object {{ $_.NextHop }});
  Dns=@($dns.ServerAddresses); Dhcp=[string]$i.Dhcp }} | ConvertTo-Json
""", label="IP-Konfiguration")
        return data[0] if data else {}

    def static_dns(self, adapter):
        """True, wenn DNS-Server manuell eingetragen sind (Registry NameServer)."""
        data = self.r.ps_json(f"""
$g = (Get-NetAdapter -Name {ps_quote(adapter)}).InterfaceGuid
$k = Get-ItemProperty ('HKLM:\\SYSTEM\\CurrentControlSet\\Services\\Tcpip\\Parameters\\Interfaces\\' + $g) -ErrorAction SilentlyContinue
[pscustomobject]@{{ NameServer=[string]$k.NameServer }} | ConvertTo-Json
""")
        return bool(data and data[0].get("NameServer"))

    def ping(self, host, timeout_ms=1500):
        data = self.r.ps_json(f"""
$p = New-Object System.Net.NetworkInformation.Ping; $ok=0; $ms=@()
1..3 | ForEach-Object {{ try {{ $x = $p.Send({ps_quote(host)}, {timeout_ms}); if ($x.Status -eq 'Success') {{ $ok++; $ms += $x.RoundtripTime }} }} catch {{}} }}
[pscustomobject]@{{ Ok=$ok; Ms=if($ms){{[int]($ms | Measure-Object -Average).Average}} }} | ConvertTo-Json
""", label=f"Ping {host}")
        if not data:
            return {"ok": 0, "ms": None, "sent": 3}
        return {"ok": int(data[0].get("Ok") or 0), "ms": data[0].get("Ms"), "sent": 3}

    def dns_resolve(self, name):
        data = self.r.ps_json(
            f"try {{ $r = Resolve-DnsName {ps_quote(name)} -DnsOnly -QuickTimeout -ErrorAction Stop |"
            " Where-Object { $_.IPAddress } | Select-Object -First 1; [pscustomobject]@{ Ip=[string]$r.IPAddress } | ConvertTo-Json }"
            " catch { [pscustomobject]@{ Ip=$null; Err=$_.Exception.Message } | ConvertTo-Json }",
            label=f"DNS {name}")
        return data[0] if data else {"Ip": None}

    def http_check(self):
        """Windows-Konnektivitätstest: erkennt Internet und Captive Portals (Hotel-WLAN)."""
        url = "http://www.msftconnecttest.com/connecttest.txt"
        self.r.log("> HTTP " + url, "cmd")
        try:
            with urllib.request.urlopen(url, timeout=6) as resp:
                body = resp.read(200).decode("ascii", errors="replace")
                return {"reachable": True, "expected": body.strip() == "Microsoft Connect Test",
                        "final_url": resp.geturl()}
        except Exception as e:  # noqa: BLE001 - jede Netzwerkstörung ist ein Befund
            return {"reachable": False, "error": str(e)}

    def proxy(self):
        r = self.r.run(["netsh", "winhttp", "show", "proxy"], echo=False)
        direct = any(w in r.out.lower() for w in ("direct access", "direkter zugriff"))
        user = {}
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                r"Software\Microsoft\Windows\CurrentVersion\Internet Settings") as k:
                for name in ("ProxyEnable", "ProxyServer", "AutoConfigURL"):
                    try:
                        user[name] = winreg.QueryValueEx(k, name)[0]
                    except OSError:
                        pass
        except ImportError:
            pass
        return {"winhttp_direct": direct, "user_enabled": bool(user.get("ProxyEnable")),
                "user_server": user.get("ProxyServer"), "pac": user.get("AutoConfigURL")}

    def wlan_events(self, hours=24):
        return self.r.ps_json(f"""
try {{ @(Get-WinEvent -FilterHashtable @{{LogName='Microsoft-Windows-WLAN-AutoConfig/Operational'; Level=2,3;
  StartTime=(Get-Date).AddHours(-{int(hours)})}} -MaxEvents 200 -ErrorAction Stop | ForEach-Object {{
  [pscustomobject]@{{ Time=$_.TimeCreated.ToString('yyyy-MM-dd HH:mm'); Id=$_.Id; Level=$_.Level;
    Msg=(($_.Message -split "`n")[0]).Trim() }} }}) | ConvertTo-Json }} catch {{ '[]' }}
""", label="Ereignisprotokoll WLAN-AutoConfig")
