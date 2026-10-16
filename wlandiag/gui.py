"""Minimale dunkle Oberfläche: Buttons links, Terminal-Ausgabe in der Mitte."""

import queue
import threading
import tkinter as tk
from tkinter import font as tkfont
from tkinter import messagebox

from . import APP_NAME, __version__
from .app import LogFile, data_dir, is_admin, open_path, relaunch_as_admin
from .engine import Engine, create_backend
from .tree import describe_tree

BG = "#0d1117"
PANEL = "#161b22"
TERM_BG = "#010409"
FG = "#e6edf3"
MUTED = "#8b949e"
BTN = "#21262d"
BTN_HOVER = "#30363d"
ACCENT = "#2f81f7"
COLORS = {
    "ok": "#3fb950", "info": "#58a6ff", "warn": "#d29922", "fail": "#f85149",
    "skip": "#6e7681", "cmd": "#6e7681", "dim": MUTED, "head": FG, "fix": "#bc8cff",
}


class App:
    def __init__(self, demo=False, autostart=True):
        self.demo = demo
        self.admin = is_admin() or demo
        self.q = queue.Queue()
        self.logfile = LogFile()
        self.busy = False
        probe, actions = create_backend(demo, self.log)
        self.engine = Engine(probe, actions, self.log)

        self.root = tk.Tk()
        self.root.title(f"{APP_NAME} {__version__}" + ("  [DEMO]" if demo else ""))
        self.root.geometry("1100x680")
        self.root.minsize(820, 480)
        self.root.configure(bg=BG)
        self._fonts()
        self._build()
        self.root.after(40, self._drain)
        self._banner()
        if autostart:
            self.root.after(400, lambda: self._start("analyse"))

    # --- Aufbau ---------------------------------------------------------------
    def _fonts(self):
        families = set(tkfont.families())
        mono = next((f for f in ("Cascadia Mono", "Consolas", "DejaVu Sans Mono") if f in families), "Courier")
        ui = next((f for f in ("Segoe UI", "DejaVu Sans") if f in families), "Helvetica")
        self.f_mono = (mono, 10)
        self.f_ui = (ui, 10)
        self.f_ui_bold = (ui, 10, "bold")
        self.f_title = (ui, 13, "bold")

    def _button(self, parent, text, cmd, color=None):
        b = tk.Button(parent, text=text, command=cmd, anchor="w", padx=14, pady=7, bd=0, relief="flat",
                      bg=BTN, fg=color or FG, activebackground=BTN_HOVER, activeforeground=color or FG,
                      font=self.f_ui, cursor="hand2", highlightthickness=0)
        b.bind("<Enter>", lambda e: b.state_ok and b.configure(bg=BTN_HOVER))
        b.bind("<Leave>", lambda e: b.configure(bg=BTN))
        b.state_ok = True
        b.pack(fill="x", padx=12, pady=3)
        return b

    def _section(self, parent, text):
        tk.Label(parent, text=text.upper(), bg=PANEL, fg=MUTED, font=(self.f_ui[0], 8, "bold"),
                 anchor="w").pack(fill="x", padx=14, pady=(14, 2))

    def _build(self):
        side = tk.Frame(self.root, bg=PANEL, width=210)
        side.pack(side="left", fill="y")
        side.pack_propagate(False)
        tk.Label(side, text="WLAN-Diagnose", bg=PANEL, fg=FG, font=self.f_title, anchor="w").pack(
            fill="x", padx=14, pady=(16, 0))
        tk.Label(side, text="HP Notebook · offline", bg=PANEL, fg=MUTED, font=self.f_ui, anchor="w").pack(
            fill="x", padx=14)

        self._section(side, "Diagnose")
        self.b_analyse = self._button(side, "▶  Analyse", lambda: self._start("analyse"))
        self.b_fix = self._button(side, "🔧  Fix", lambda: self._start("fix"))
        self.b_trouble = self._button(side, "🧭  Troubleshooting", lambda: self._start("troubleshoot"))
        self._section(side, "Werkzeuge")
        self.b_tree = self._button(side, "☰  Aktionsbaum", self._show_tree)
        self.b_report = self._button(side, "📄  WLAN-Bericht", lambda: self._start("report"))
        self._button(side, "📁  Log-Ordner", lambda: open_path(data_dir()))
        self._button(side, "⌫  Ausgabe leeren", self._clear)
        self.actions = [self.b_analyse, self.b_fix, self.b_trouble, self.b_report]

        bottom = tk.Frame(side, bg=PANEL)
        bottom.pack(side="bottom", fill="x", pady=12)
        self.invasive = tk.BooleanVar(value=False)
        tk.Checkbutton(bottom, text="Tiefgreifende Reparaturen\nerlauben (Winsock, TCP/IP,\nTreiber, Proxy)",
                       variable=self.invasive, bg=PANEL, fg=MUTED, selectcolor=BTN, activebackground=PANEL,
                       activeforeground=FG, font=(self.f_ui[0], 9), justify="left", anchor="w",
                       highlightthickness=0, bd=0).pack(fill="x", padx=10, pady=(0, 8))
        self.b_stop = self._button(bottom, "■  Stopp", self._stop, color=COLORS["fail"])
        if not self.admin:
            self._button(bottom, "🛡  Als Admin neu starten", self._elevate, color=COLORS["warn"])

        main = tk.Frame(self.root, bg=BG)
        main.pack(side="left", fill="both", expand=True)
        term = tk.Frame(main, bg=TERM_BG, highlightthickness=1, highlightbackground="#30363d")
        term.pack(fill="both", expand=True, padx=12, pady=(12, 6))
        self.text = tk.Text(term, bg=TERM_BG, fg=FG, insertbackground=FG, font=self.f_mono, bd=0,
                            padx=12, pady=10, wrap="word", highlightthickness=0, state="disabled",
                            selectbackground="#264f78")
        sb = tk.Scrollbar(term, command=self.text.yview, bg=PANEL, troughcolor=TERM_BG, bd=0,
                          activebackground=BTN_HOVER, highlightthickness=0, width=12)
        self.text.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.text.pack(side="left", fill="both", expand=True)
        for tag, color in COLORS.items():
            self.text.tag_configure(tag, foreground=color)
        self.text.tag_configure("head", font=(self.f_mono[0], self.f_mono[1], "bold"))

        self.status = tk.Label(main, text="", bg=BG, fg=MUTED, font=(self.f_ui[0], 9), anchor="w")
        self.status.pack(fill="x", padx=14, pady=(0, 8))
        self._set_status("Bereit")

    # --- Ausgabe ------------------------------------------------------------
    def log(self, line, tag="dim"):
        """Thread-sicher: Zeilen werden über eine Queue an die Oberfläche übergeben."""
        self.q.put((line, tag))
        self.logfile.write(line, tag)

    def _drain(self):
        try:
            lines = []
            while True:
                lines.append(self.q.get_nowait())
        except queue.Empty:
            pass
        if lines:
            self.text.configure(state="normal")
            for line, tag in lines:
                self.text.insert("end", line + "\n", tag)
            self.text.configure(state="disabled")
            self.text.see("end")
        self.root.after(40, self._drain)

    def _clear(self):
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.configure(state="disabled")

    def _banner(self):
        self.log(f"{APP_NAME} {__version__}", "head")
        self.log("Rechte: " + ("Administrator" if self.admin else "Standardbenutzer (Reparaturen brauchen Adminrechte)"),
                 "ok" if self.admin else "warn")
        if self.demo:
            self.log("DEMO-Modus: simuliertes HP EliteBook mit Flugmodus, Energiesparproblem, "
                     "fehlender IP-Adresse und DNS-Störung.", "info")
        self.log(f"Protokoll: {self.logfile.path}", "dim")

    def _set_status(self, text):
        mode = "Admin" if self.admin else "kein Admin"
        self.status.configure(text=f"{text}   ·   {mode}" + ("   ·   Demo" if self.demo else ""))

    # --- Aktionen -------------------------------------------------------------
    def _start(self, what):
        if self.busy:
            return
        if what in ("fix", "troubleshoot"):
            if not self.admin:
                if messagebox.askyesno(APP_NAME, "Reparaturen brauchen Administratorrechte.\n\n"
                                                 "Jetzt als Administrator neu starten?"):
                    self._elevate()
                return
            extra = ("\n\nTiefgreifende Reparaturen sind freigegeben (Winsock/TCP-IP-Reset, Treiber "
                     "neu binden, Proxy zurücksetzen)." if self.invasive.get() else "")
            if not messagebox.askyesno(APP_NAME, "Automatische Reparaturen ändern Netzwerkeinstellungen und "
                                                 "trennen die WLAN-Verbindung ggf. kurz." + extra + "\n\nFortfahren?"):
                return
        self.engine.allow_invasive = self.invasive.get()
        func = {"analyse": self.engine.analyse, "fix": self.engine.fix,
                "troubleshoot": self.engine.troubleshoot, "report": self._report}[what]
        self.busy = True
        for b in self.actions:
            b.configure(state="disabled")
        self._set_status({"analyse": "Analyse läuft …", "fix": "Reparatur läuft …",
                          "troubleshoot": "Troubleshooting läuft …", "report": "Bericht wird erstellt …"}[what])
        threading.Thread(target=self._run, args=(func,), daemon=True).start()

    def _run(self, func):
        try:
            func()
        except Exception as e:  # noqa: BLE001
            self.log(f"Unerwarteter Fehler: {e}", "fail")
        finally:
            self.root.after(0, self._done)

    def _done(self):
        self.busy = False
        for b in self.actions:
            b.configure(state="normal")
        self._set_status("Bereit")

    def _report(self):
        path = self.engine.wlan_report()
        if path:
            open_path(path)

    def _show_tree(self):
        self.log("")
        self.log("══ Aktionsbaum (Reihenfolge des Troubleshootings) ══", "head")
        for line, tag in describe_tree():
            self.log(line, tag)

    def _stop(self):
        if self.busy:
            self.engine.cancel.set()
            self.log("Stopp angefordert, laufender Schritt wird noch beendet …", "warn")

    def _elevate(self):
        if relaunch_as_admin():
            self.root.destroy()
        else:
            self.log("Neustart als Administrator abgelehnt oder nicht möglich.", "warn")

    def run(self):
        self.root.mainloop()


def main(demo=False, autostart=True):
    App(demo=demo, autostart=autostart).run()
