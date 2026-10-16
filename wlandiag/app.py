"""Gemeinsame Helfer für GUI und Kommandozeile: Logdatei, Adminrechte, Neustart als Admin."""

import ctypes
import os
import subprocess
import sys
from datetime import datetime

from . import APP_NAME
from .runner import IS_WINDOWS


def data_dir():
    base = os.environ.get("LOCALAPPDATA") if IS_WINDOWS else os.path.expanduser("~/.local/share")
    path = os.path.join(base or os.path.expanduser("~"), APP_NAME, "logs")
    os.makedirs(path, exist_ok=True)
    return path


class LogFile:
    """Schreibt jede Ausgabezeile mit Zeitstempel in eine Datei pro Programmstart."""

    def __init__(self):
        self.path = os.path.join(data_dir(), datetime.now().strftime("diagnose-%Y%m%d-%H%M%S.txt"))
        self._fh = open(self.path, "a", encoding="utf-8")

    def write(self, line, tag=""):
        self._fh.write(f"{datetime.now():%H:%M:%S} {line}\n")
        self._fh.flush()


def is_admin():
    if not IS_WINDOWS:
        return os.geteuid() == 0 if hasattr(os, "geteuid") else False
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:  # noqa: BLE001
        return False


def relaunch_as_admin(extra_args=()):
    """Startet das Programm per UAC-Abfrage mit Administratorrechten neu."""
    if not IS_WINDOWS:
        return False
    if getattr(sys, "frozen", False):
        exe, args = sys.executable, list(sys.argv[1:])
    else:
        exe, args = sys.executable, ["-m", "wlandiag"] + list(sys.argv[1:])
    args += [a for a in extra_args if a not in args]
    workdir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    rc = ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, subprocess.list2cmdline(args), workdir, 1)
    return rc > 32


def open_path(path):
    if IS_WINDOWS:
        os.startfile(path)  # noqa: S606
    else:
        subprocess.Popen(["xdg-open", path])
