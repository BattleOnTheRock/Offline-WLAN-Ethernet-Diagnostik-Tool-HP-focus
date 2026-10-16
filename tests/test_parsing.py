import unittest

from wlandiag.probe_windows import parse_netsh_interfaces, parse_powercfg_indices

NETSH_DE = """
Es ist 1 Schnittstelle auf dem System vorhanden:

    Name                   : WLAN
    Beschreibung           : Intel(R) Wi-Fi 6 AX201 160MHz
    GUID                   : 1234
    Physische Adresse      : a4:b1:c1:12:34:56
    Status                 : Verbunden
    SSID                   : FRITZ!Box 7590 XY
    AP BSSID               : 3c:a6:2f:11:22:33
    Band                   : 5 GHz
    Kanal                  : 36
    Funktyp                : 802.11ax
    Authentifizierung      : WPA2-Personal
    Empfangsrate (MBit/s)  : 1201
    Übertragungsrate (MBit/s) : 960
    Signal                 : 78%
    Profil                 : FRITZ!Box 7590 XY
"""

NETSH_EN_DISC = """
There is 1 interface on the system:

    Name                   : Wi-Fi
    Description            : Realtek RTL8852BE WiFi 6 802.11ax PCIe Adapter
    State                  : disconnected
    Radio status           : Hardware On
                             Software Off
"""

POWERCFG = """Power Scheme GUID: 381b4222-f694-41f0-9685-ff5bb260df2e  (Balanced)
  Subgroup GUID: 19cbb8fa-5279-450e-9fac-8a3d5fedd0c1  (Wireless Adapter Settings)
    Power Setting GUID: 12bbebe6-58d6-4636-95bb-3217ef867c1a  (Power Saving Mode)
      Possible Setting Index: 000
      Possible Setting Friendly Name: Maximum Performance
      Possible Setting Index: 003
      Possible Setting Friendly Name: Maximum Power Saving
    Current AC Power Setting Index: 0x00000000
    Current DC Power Setting Index: 0x00000002
"""


class ParseTests(unittest.TestCase):
    def test_netsh_german_connected(self):
        itf = parse_netsh_interfaces(NETSH_DE)[0]
        self.assertTrue(itf["connected"])
        self.assertEqual(itf["ssid"], "FRITZ!Box 7590 XY")
        self.assertEqual(itf["bssid"], "3c:a6:2f:11:22:33")
        self.assertEqual(itf["signal_pct"], 78)
        self.assertEqual(itf["tx"], "960")
        self.assertEqual(itf["auth"], "WPA2-Personal")

    def test_netsh_english_disconnected(self):
        itf = parse_netsh_interfaces(NETSH_EN_DISC)[0]
        self.assertEqual(itf["name"], "Wi-Fi")
        self.assertFalse(itf["connected"])
        self.assertIsNone(itf["signal_pct"])

    def test_powercfg(self):
        self.assertEqual(parse_powercfg_indices(POWERCFG), {"ac": 0, "dc": 2})
        self.assertIsNone(parse_powercfg_indices("Fehler"))


if __name__ == "__main__":
    unittest.main()
