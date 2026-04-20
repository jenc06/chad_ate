"""
gui.py — Tkinter GUI for the ATE power sweep demo.

Layout
------
  ┌─────────────────────────────────────────────────────┐
  │  Start  Stop  Step  Freq  [Run Sweep]               │  ← controls
  ├─────────────────────────────────────────────────────┤
  │                                                     │
  │          matplotlib gain-vs-Pin plot                │
  │                                                     │
  ├─────────────────────────────────────────────────────┤
  │  ████████░░░░  progress bar                         │
  │  status text                                        │
  └─────────────────────────────────────────────────────┘

The sweep runs in a background thread so the GUI stays responsive.
"""

from __future__ import annotations

import os
import threading
import tkinter as tk
from tkinter import ttk, messagebox

import matplotlib
matplotlib.use("TkAgg")
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib.figure import Figure
import numpy as np

from instruments import connect_instruments
from sweep import run_sweep, SweepResult
from analysis import find_p1db, CompressionResult

_SIM_YAML = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sim_config.yaml")

# ── Plot colours ──────────────────────────────────────────────────────────────
_COLOR_GAIN = "#2196F3"        # measured gain line
_COLOR_BASELINE = "#9E9E9E"    # linear baseline
_COLOR_MINUS1DB = "#FF9800"    # baseline − 1 dB reference
_COLOR_P1DB = "#F44336"        # P1dB marker / annotation


class ATEApp(tk.Tk):
    """Main application window."""

    def __init__(self) -> None:
        super().__init__()
        self.title("ATE Power Sweep — PyVISA-sim Demo")
        self.minsize(820, 560)

        self._sweep_result: SweepResult | None = None
        self._compression: CompressionResult | None = None

        self._build_ui()
        self._reset_plot()

    # ── UI construction ───────────────────────────────────────────────────

    def _build_ui(self) -> None:
        # ── Control bar ───────────────────────────────────────────────────
        ctrl = ttk.Frame(self, padding=(8, 6))
        ctrl.pack(side=tk.TOP, fill=tk.X)

        fields = [
            ("Start (dBm):", "start", -30.0, 7),
            ("Stop (dBm):",  "stop",   10.0, 7),
            ("Step (dB):",   "step",    1.0, 5),
            ("Freq (GHz):",  "freq",    1.0, 6),
        ]
        self._vars: dict[str, tk.DoubleVar] = {}
        col = 0
        for label, key, default, width in fields:
            ttk.Label(ctrl, text=label).grid(row=0, column=col, padx=(6, 2))
            col += 1
            var = tk.DoubleVar(value=default)
            self._vars[key] = var
            ttk.Entry(ctrl, textvariable=var, width=width).grid(row=0, column=col, padx=(0, 6))
            col += 1

        self._run_btn = ttk.Button(ctrl, text="Run Sweep", command=self._on_run)
        self._run_btn.grid(row=0, column=col, padx=12)

        # ── Matplotlib canvas ─────────────────────────────────────────────
        plot_frame = ttk.Frame(self)
        plot_frame.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 4))

        self._fig = Figure(figsize=(9, 5), dpi=100, tight_layout=True)
        self._ax = self._fig.add_subplot(111)

        self._canvas = FigureCanvasTkAgg(self._fig, master=plot_frame)
        self._canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

        toolbar = NavigationToolbar2Tk(self._canvas, plot_frame, pack_toolbar=False)
        toolbar.update()
        toolbar.pack(side=tk.BOTTOM, fill=tk.X)

        # ── Progress + status ─────────────────────────────────────────────
        bottom = ttk.Frame(self, padding=(8, 2))
        bottom.pack(side=tk.BOTTOM, fill=tk.X)

        self._progress = ttk.Progressbar(bottom, orient=tk.HORIZONTAL, mode="determinate")
        self._progress.pack(fill=tk.X, pady=(0, 2))

        self._status_var = tk.StringVar(value="Ready — press Run Sweep to begin.")
        ttk.Label(bottom, textvariable=self._status_var, anchor=tk.W).pack(fill=tk.X)

    # ── Plot helpers ──────────────────────────────────────────────────────

    def _reset_plot(self) -> None:
        ax = self._ax
        ax.clear()
        ax.set_xlabel("Input Power (dBm)")
        ax.set_ylabel("Gain (dB)")
        ax.set_title("Amplifier Gain vs Input Power")
        ax.grid(True, alpha=0.3)
        ax.text(
            0.5, 0.5, "Press 'Run Sweep' to begin",
            ha="center", va="center", transform=ax.transAxes,
            fontsize=13, color="#BDBDBD",
        )
        self._canvas.draw()

    def _update_plot(self) -> None:
        result = self._sweep_result
        compression = self._compression
        ax = self._ax
        ax.clear()

        # ── Measured gain trace ───────────────────────────────────────────
        ax.plot(
            result.pin_dbm, result.gain_db,
            color=_COLOR_GAIN, marker="o", markersize=4, linewidth=1.8,
            label="Measured Gain",
        )

        if compression:
            bl = compression.baseline_gain_db

            # Linear baseline
            ax.axhline(
                bl, color=_COLOR_BASELINE, linestyle="--", linewidth=1.2,
                label=f"Linear Baseline  {bl:.1f} dB",
            )
            # Baseline − 1 dB reference
            ax.axhline(
                bl - 1.0, color=_COLOR_MINUS1DB, linestyle=":", linewidth=1.2,
                label="Baseline − 1 dB",
            )

            # Vertical line at P1dB_in
            ax.axvline(
                compression.p1db_in_dbm, color=_COLOR_P1DB,
                linestyle="--", linewidth=1.2, alpha=0.6,
            )

            # Star marker at the compression point
            ax.plot(
                compression.p1db_in_dbm, bl - 1.0,
                marker="*", markersize=16, color=_COLOR_P1DB, zorder=6,
                label=(
                    f"P1dB_in = {compression.p1db_in_dbm:.1f} dBm  |  "
                    f"P1dB_out = {compression.p1db_out_dbm:.1f} dBm"
                ),
            )

            # Annotation box
            ax.annotate(
                (
                    f"P1dB\n"
                    f"Pin  = {compression.p1db_in_dbm:.1f} dBm\n"
                    f"Pout = {compression.p1db_out_dbm:.1f} dBm"
                ),
                xy=(compression.p1db_in_dbm, bl - 1.0),
                xytext=(compression.p1db_in_dbm - 12, bl - 6),
                arrowprops=dict(arrowstyle="->", color=_COLOR_P1DB, lw=1.3),
                fontsize=9, color=_COLOR_P1DB,
                bbox=dict(
                    boxstyle="round,pad=0.4",
                    facecolor="white", edgecolor=_COLOR_P1DB, alpha=0.9,
                ),
            )

            # Shade the compressed region
            x_start = compression.p1db_in_dbm
            x_end = float(result.pin_dbm[-1])
            ax.axvspan(x_start, x_end, alpha=0.07, color=_COLOR_P1DB, label="_nolegend_")

        ax.set_xlabel("Input Power (dBm)")
        ax.set_ylabel("Gain (dB)")
        ax.set_title("Amplifier Gain vs Input Power (Simulated ATE)")
        ax.legend(loc="lower left", fontsize=9, framealpha=0.9)
        ax.grid(True, alpha=0.3)
        self._fig.tight_layout()
        self._canvas.draw()

        # Status bar summary
        if compression:
            self._status_var.set(
                f"Sweep complete  |  "
                f"P1dB_in = {compression.p1db_in_dbm:.1f} dBm  |  "
                f"P1dB_out = {compression.p1db_out_dbm:.1f} dBm  |  "
                f"Baseline gain = {compression.baseline_gain_db:.1f} dB"
            )
        else:
            self._status_var.set(
                "Sweep complete — P1dB not detected within the swept range. "
                "Try extending the stop power."
            )

    # ── Sweep execution ───────────────────────────────────────────────────

    def _on_run(self) -> None:
        self._run_btn.config(state=tk.DISABLED)
        self._status_var.set("Connecting to simulated instruments…")
        self._progress["value"] = 0
        self._reset_plot()
        threading.Thread(target=self._sweep_thread, daemon=True).start()

    def _sweep_thread(self) -> None:
        try:
            sig_gen, spec_an = connect_instruments(_SIM_YAML)

            start = self._vars["start"].get()
            stop  = self._vars["stop"].get()
            step  = self._vars["step"].get()
            freq  = self._vars["freq"].get() * 1e9

            total = int(round((stop - start) / step)) + 1
            self.after(0, lambda: self._progress.configure(maximum=total, value=0))
            self.after(0, lambda: self._status_var.set("Sweep running…"))

            def _progress_cb(done: int, _total: int) -> None:
                self.after(0, lambda d=done: self._progress.configure(value=d))
                self.after(0, lambda d=done, t=_total: self._status_var.set(
                    f"Sweeping… {d}/{t} points  "
                    f"(Pin = {start + (d - 1) * step:.0f} dBm)"
                ))

            result = run_sweep(sig_gen, spec_an, start, stop, step, freq, _progress_cb)
            compression = find_p1db(result)

            self._sweep_result = result
            self._compression = compression
            self.after(0, self._update_plot)

        except Exception as exc:
            self.after(0, lambda e=exc: messagebox.showerror("Sweep Error", str(e)))
            self.after(0, lambda: self._status_var.set("Error — see dialog for details."))

        finally:
            self.after(0, lambda: self._run_btn.config(state=tk.NORMAL))


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    app = ATEApp()
    app.mainloop()


if __name__ == "__main__":
    main()
