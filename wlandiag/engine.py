"""Ablaufsteuerung: Analyse (nur lesen), Fix (Befunde der letzten Analyse
reparieren) und Troubleshooting (kompletter Aktionsbaum mit Reparaturen)."""

import threading
from datetime import datetime

from . import checks as C
from .runner import Runner
from .tree import FIXES, NODES, TREE

TAG = {C.OK: "ok", C.INFO: "info", C.WARN: "warn", C.FAIL: "fail", C.SKIP: "skip"}


class Cancelled(Exception):
    pass


def create_backend(demo, log):
    runner = Runner(log)
    if demo:
        from .demo import DemoActions, DemoProbe, SimState
        state = SimState()
        return DemoProbe(runner, state), DemoActions(runner, state)
    from .actions_windows import WindowsActions
    from .probe_windows import WindowsProbe
    return WindowsProbe(runner), WindowsActions(runner)


class Engine:
    def __init__(self, probe, actions, log, allow_invasive=False):
        self.probe, self.actions, self.log = probe, actions, log
        self.allow_invasive = allow_invasive
        self.cancel = threading.Event()
        self.last_bad = None     # Check-IDs mit Befund aus der letzten Analyse

    # --- Ausgabe ------------------------------------------------------------
    def _print(self, title, res, indent=""):
        self.log(f"{indent}[{res.status:^4}] {title:<26} {res.summary}", TAG[res.status])
        for d in res.details:
            self.log(f"{indent}       {d}", "dim")

    def _recommend(self, node, res):
        fixes = res.fixes if res.fixes is not None else node.fixes
        if fixes:
            self.log("       Automatisch: " + " → ".join(FIXES[f].title for f in fixes), "fix")
        hint = res.hint or node.hint
        if hint:
            self.log("       Manuell: " + hint, "dim")

    def _check(self, node, ctx):
        if self.cancel.is_set():
            raise Cancelled()
        try:
            return node.check(ctx)
        except Cancelled:
            raise
        except Exception as e:  # noqa: BLE001 - ein defekter Check darf den Lauf nicht beenden
            return C.Result(C.WARN, f"Prüfung fehlgeschlagen: {e}")

    # --- Reparatur ----------------------------------------------------------
    def _repair(self, node, res, ctx, report):
        fixes = res.fixes if res.fixes is not None else node.fixes
        for fid in fixes:
            if self.cancel.is_set():
                raise Cancelled()
            fx = FIXES[fid]
            if fx.invasive and not self.allow_invasive:
                self.log(f"       ⏭ {fx.title}: übersprungen (tiefgreifend, nicht freigegeben)", "skip")
                report["skipped_invasive"].append(fx.title)
                continue
            self.log(f"       ⚙ {fx.title}", "fix")
            func = getattr(self.actions, fid)
            try:
                if fid == "reinstall_driver":
                    ok, msg = func(ctx.adapter_name, (ctx.adapter or {}).get("PnpId"))
                else:
                    ok, msg = func(ctx.adapter_name)
            except Exception as e:  # noqa: BLE001
                ok, msg = False, str(e)
            self.log(f"         {'erfolgreich' if ok else 'fehlgeschlagen'}: {msg}", "ok" if ok else "fail")
            report["applied"].append(fx.title)
            if fx.reboot and ok:
                report["reboot"] = True
                return C.Result(res.status, res.summary + " (Neustart ausstehend)", res.details)
            new = self._check(node, ctx)
            self._print("Nachtest", new, indent="  ")
            if not new.bad:
                report["fixed"].append(f"{node.title}: {res.summary}")
                return new
            res = new
        hint = res.hint or node.hint
        if hint:
            self.log("       Manuell: " + hint, "warn")
        return res

    # --- Durchlauf ----------------------------------------------------------
    def _walk(self, mode, targets=None):
        self.cancel.clear()
        repair = mode != "Analyse"
        ctx = C.Ctx(self.probe, self.actions, self.log)
        report = {"fixed": [], "applied": [], "skipped_invasive": [], "reboot": False}
        stamp = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
        self.log("")
        self.log(f"══ {mode} gestartet {stamp} ══", "head")
        if repair and not self.allow_invasive:
            self.log("Tiefgreifende Reparaturen (Winsock/TCP-IP/Treiber/Proxy) sind nicht freigegeben.", "dim")
        try:
            for node in TREE:
                missing = [r for r in node.requires
                           if r not in ctx.results or ctx.results[r].status in (C.FAIL, C.SKIP)]
                if missing:
                    res = C.Result(C.SKIP, f"übersprungen (wegen {NODES[missing[0]].title})")
                    ctx.results[node.id] = res
                    self._print(node.title, res)
                    continue
                res = self._check(node, ctx)
                self._print(node.title, res)
                if res.bad:
                    if repair and (targets is None or node.id in targets):
                        res = self._repair(node, res, ctx, report)
                    elif not repair:
                        self._recommend(node, res)
                ctx.results[node.id] = res
        except Cancelled:
            self.log("Abgebrochen.", "warn")
            return ctx.results
        self._summary(mode, ctx, report)
        if mode == "Analyse":
            # Übersprungene Prüfungen zählen mit: hinter einem Fehler können weitere Probleme stecken.
            self.last_bad = {k for k, v in ctx.results.items()
                             if not k.startswith("_") and (v.bad or v.status == C.SKIP)}
        return ctx.results

    def _summary(self, mode, ctx, report):
        res = {k: v for k, v in ctx.results.items() if not k.startswith("_")}
        bad = [(k, v) for k, v in res.items() if v.bad]
        fails = sum(1 for _, v in bad if v.status == C.FAIL)
        self.log("─" * 72, "dim")
        if report["fixed"]:
            self.log(f"Behoben ({len(report['fixed'])}):", "ok")
            for f in report["fixed"]:
                self.log("  ✔ " + f, "ok")
        if bad:
            self.log(f"Offen: {fails} Fehler, {len(bad) - fails} Warnungen", "fail" if fails else "warn")
            for k, v in bad:
                self.log(f"  • {k}: {v.summary}", TAG[v.status])
        else:
            self.log("Keine offenen Probleme gefunden. WLAN funktioniert.", "ok")
        if report["skipped_invasive"]:
            self.log("Übersprungen (Freigabe nötig): " + ", ".join(dict.fromkeys(report["skipped_invasive"])), "skip")
        if report["reboot"]:
            self.log("⚠ Neustart erforderlich, damit die Netzwerk-Resets wirken. Danach erneut prüfen.", "warn")
        if mode == "Analyse" and bad:
            self.log("Tipp: 'Fix' repariert die gefundenen Probleme, 'Troubleshooting' arbeitet den ganzen Baum ab.",
                     "dim")
        self.log(f"══ {mode} beendet ══", "head")

    # --- Öffentliche Befehle --------------------------------------------------
    def analyse(self):
        return self._walk("Analyse")

    def fix(self):
        if self.last_bad is None:
            self.log("Noch keine Analyse gelaufen: führe Troubleshooting mit Reparaturen aus.", "dim")
            return self._walk("Fix")
        if not self.last_bad:
            self.log("Letzte Analyse ohne Befund, nichts zu reparieren.", "ok")
            return {}
        return self._walk("Fix", targets=set(self.last_bad))

    def troubleshoot(self):
        return self._walk("Troubleshooting")

    def wlan_report(self):
        self.log("")
        self.log("══ WLAN-Bericht (netsh wlan show wlanreport) ══", "head")
        ok, msg = self.actions.wlan_report(None)
        self.log(("Bericht erstellt: " if ok else "Fehler: ") + msg, "ok" if ok else "fail")
        return msg if ok else None
