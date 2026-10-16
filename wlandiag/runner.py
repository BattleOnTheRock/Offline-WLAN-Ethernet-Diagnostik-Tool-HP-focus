"""Ausführen von Systembefehlen (cmd-Tools und PowerShell) ohne Konsolenfenster."""

import json
import subprocess
import sys
from dataclasses import dataclass

IS_WINDOWS = sys.platform == "win32"
CREATE_NO_WINDOW = 0x08000000

# PowerShell soll UTF-8 liefern, damit Umlaute (deutsches Windows) sauber ankommen.
_PS_PREFIX = (
    "$ErrorActionPreference='Stop';"
    "try{[Console]::OutputEncoding=[Text.Encoding]::UTF8}catch{};"
    "$ProgressPreference='SilentlyContinue';"
)


@dataclass
class CmdResult:
    code: int
    out: str
    err: str

    @property
    def ok(self):
        return self.code == 0


def ps_quote(value):
    """String als PowerShell-Literal in einfachen Anführungszeichen."""
    return "'" + str(value).replace("'", "''") + "'"


class Runner:
    """Führt Befehle aus und meldet jeden Aufruf an einen optionalen Logger."""

    def __init__(self, log=None):
        self.log = log or (lambda line, tag="cmd": None)

    def run(self, args, timeout=60, echo=True):
        if echo:
            self.log("> " + " ".join(args), "cmd")
        kwargs = {}
        if IS_WINDOWS:
            kwargs["creationflags"] = CREATE_NO_WINDOW
        try:
            p = subprocess.run(args, capture_output=True, timeout=timeout, **kwargs)
        except FileNotFoundError:
            return CmdResult(127, "", f"Befehl nicht gefunden: {args[0]}")
        except subprocess.TimeoutExpired:
            return CmdResult(124, "", f"Zeitüberschreitung nach {timeout}s")
        # cmd-Tools wie netsh/ipconfig schreiben in der OEM-Codepage (z. B. cp850).
        enc = "oem" if IS_WINDOWS else "utf-8"
        return CmdResult(
            p.returncode,
            p.stdout.decode(enc, errors="replace"),
            p.stderr.decode(enc, errors="replace"),
        )

    def ps(self, script, timeout=60, echo=False, label=None):
        if label:
            self.log("> PowerShell: " + label, "cmd")
        args = [
            "powershell.exe", "-NoProfile", "-NonInteractive",
            "-ExecutionPolicy", "Bypass", "-Command", _PS_PREFIX + script,
        ]
        if echo:
            self.log("> " + script, "cmd")
        kwargs = {"creationflags": CREATE_NO_WINDOW} if IS_WINDOWS else {}
        try:
            p = subprocess.run(args, capture_output=True, timeout=timeout, **kwargs)
        except FileNotFoundError:
            return CmdResult(127, "", "powershell.exe nicht gefunden")
        except subprocess.TimeoutExpired:
            return CmdResult(124, "", f"Zeitüberschreitung nach {timeout}s")
        return CmdResult(
            p.returncode,
            p.stdout.decode("utf-8", errors="replace"),
            p.stderr.decode("utf-8", errors="replace"),
        )

    def ps_json(self, script, timeout=60, label=None):
        """PowerShell-Skript ausführen, dessen Ausgabe per ConvertTo-Json kommt.

        Gibt immer eine Liste zurück (leer bei Fehler oder keiner Ausgabe)."""
        r = self.ps(script, timeout=timeout, label=label)
        text = r.out.strip()
        if not r.ok or not text:
            return []
        try:
            data = json.loads(text)
        except ValueError:
            return []
        if data is None:
            return []
        return data if isinstance(data, list) else [data]
