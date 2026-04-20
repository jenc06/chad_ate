"""
sweep.py — Power sweep loop for the ATE demo.

Drives the signal generator from start_dbm to stop_dbm in step_dbm increments,
reads output power from the spectrum analyzer at each point, and returns the
collected data as a SweepResult dataclass.

Can also be run directly as a CLI script:
    python sweep.py
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Callable, Optional

import numpy as np

from instruments import SignalGenerator, SpectrumAnalyzer, connect_instruments

# Default sweep parameters
DEFAULT_START_DBM: float = -30.0
DEFAULT_STOP_DBM: float = 10.0
DEFAULT_STEP_DBM: float = 1.0
DEFAULT_FREQ_HZ: float = 1.0e9
SETTLE_TIME_S: float = 0.02   # Simulated settle / integration time per point


@dataclass
class SweepResult:
    """Container for a completed power sweep."""
    pin_dbm: np.ndarray   # Commanded input power levels
    pout_dbm: np.ndarray  # Measured output power levels
    gain_db: np.ndarray   # Calculated gain = Pout - Pin


def run_sweep(
    sig_gen: SignalGenerator,
    spec_an: SpectrumAnalyzer,
    start_dbm: float = DEFAULT_START_DBM,
    stop_dbm: float = DEFAULT_STOP_DBM,
    step_dbm: float = DEFAULT_STEP_DBM,
    freq_hz: float = DEFAULT_FREQ_HZ,
    progress_cb: Optional[Callable[[int, int], None]] = None,
) -> SweepResult:
    """
    Perform a CW power sweep and return measured Pin, Pout, and Gain arrays.

    Parameters
    ----------
    sig_gen     : configured SignalGenerator instance
    spec_an     : configured SpectrumAnalyzer instance
    start_dbm   : first output power level (dBm)
    stop_dbm    : last output power level (dBm, inclusive)
    step_dbm    : power step size (dB)
    freq_hz     : CW frequency (Hz)
    progress_cb : optional callable(done: int, total: int) for progress updates
    """
    pin_points = np.arange(start_dbm, stop_dbm + step_dbm * 0.5, step_dbm)
    pout_points = np.zeros_like(pin_points)
    total = len(pin_points)

    # ── Instrument setup ─────────────────────────────────────────────────
    sig_gen.reset()
    spec_an.reset()

    sig_gen.set_frequency(freq_hz)
    spec_an.set_center_frequency(freq_hz)
    spec_an.set_span(1.0e6)
    spec_an.set_ref_level(30.0)

    sig_gen.output_on()

    # ── Sweep loop ────────────────────────────────────────────────────────
    try:
        for i, pin in enumerate(pin_points):
            sig_gen.set_power(float(pin))
            spec_an.update_input_power(float(pin))   # keep model in sync
            time.sleep(SETTLE_TIME_S)
            pout_points[i] = spec_an.get_peak_power()

            if progress_cb:
                progress_cb(i + 1, total)
    finally:
        sig_gen.output_off()

    gain = pout_points - pin_points
    return SweepResult(pin_dbm=pin_points, pout_dbm=pout_points, gain_db=gain)


# ── CLI entry point ───────────────────────────────────────────────────────────

def _cli() -> None:
    import sys

    yaml_path = os.path.join(os.path.dirname(__file__), "sim_config.yaml")
    print("Connecting to simulated instruments…")
    sig_gen, spec_an = connect_instruments(yaml_path)
    print(f"  SigGen : {sig_gen.identify()}")
    print(f"  SpecAn : {spec_an.identify()}")
    print()

    def _progress(done: int, total: int) -> None:
        bar = "#" * done + "." * (total - done)
        print(f"\r  [{bar}] {done}/{total}", end="", flush=True)

    print("Running sweep…")
    result = run_sweep(sig_gen, spec_an, progress_cb=_progress)
    print("\n")
    print(f"{'Pin (dBm)':>10}  {'Pout (dBm)':>10}  {'Gain (dB)':>10}")
    print("-" * 36)
    for pin, pout, gain in zip(result.pin_dbm, result.pout_dbm, result.gain_db):
        print(f"{pin:>10.1f}  {pout:>10.2f}  {gain:>10.2f}")

    from analysis import find_p1db
    compression = find_p1db(result)
    if compression:
        print(f"\nP1dB_in  = {compression.p1db_in_dbm:.2f} dBm")
        print(f"P1dB_out = {compression.p1db_out_dbm:.2f} dBm")
        print(f"Baseline gain = {compression.baseline_gain_db:.2f} dB")
    else:
        print("\nP1dB not detected within sweep range.")


if __name__ == "__main__":
    _cli()
