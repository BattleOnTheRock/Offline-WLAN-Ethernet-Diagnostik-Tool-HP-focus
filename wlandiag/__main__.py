"""Einstieg: GUI (Standard) oder Kommandozeile (--cli)."""

import argparse
import sys

from . import APP_NAME, __version__

ANSI = {"ok": "32", "info": "36", "warn": "33", "fail": "31", "skip": "90", "cmd": "90",
        "dim": "90", "head": "1", "fix": "35"}


def cli(args):
    from .app import LogFile
    from .engine import Engine, create_backend
    from .tree import describe_tree

    logfile = LogFile()
    color = sys.stdout.isatty() and not args.no_color

    def log(line, tag="dim"):
        logfile.write(line, tag)
        print(f"\033[{ANSI.get(tag, '0')}m{line}\033[0m" if color else line, flush=True)

    if args.command == "tree":
        for line, tag in describe_tree():
            log(line, tag)
        return 0
    probe, actions = create_backend(args.demo, log)
    if args.demo:
        probe.s.delay = 0
    engine = Engine(probe, actions, log, allow_invasive=args.invasive)
    if args.command == "analyse":
        results = engine.analyse()
    elif args.command == "fix":
        engine.analyse()
        results = engine.fix()
    elif args.command == "troubleshoot":
        results = engine.troubleshoot()
    else:
        return 0 if engine.wlan_report() else 1
    log(f"Protokoll: {logfile.path}")
    return 1 if any(r.status == "FAIL" for k, r in results.items() if not k.startswith("_")) else 0


def main():
    p = argparse.ArgumentParser(prog="wlandiag", description=f"{APP_NAME} {__version__}")
    p.add_argument("--demo", action="store_true", help="simuliertes Gerät statt echter Systemabfragen")
    p.add_argument("--cli", dest="command", choices=["analyse", "fix", "troubleshoot", "tree", "report"],
                   help="ohne Oberfläche ausführen")
    p.add_argument("--invasive", action="store_true", help="tiefgreifende Reparaturen erlauben (nur --cli)")
    p.add_argument("--no-autostart", action="store_true", help="beim Start keine Analyse ausführen")
    p.add_argument("--no-color", action="store_true")
    args = p.parse_args()
    if args.command:
        sys.exit(cli(args))
    from .gui import main as gui_main
    gui_main(demo=args.demo, autostart=not args.no_autostart)


if __name__ == "__main__":
    main()
