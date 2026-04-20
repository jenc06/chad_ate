"""
instruments.py — SCPI wrapper classes for the simulated ATE bench.

SignalGenerator  → GPIB::1  (sets frequency and output power)
SpectrumAnalyzer → GPIB::2  (measures output power)

The SpectrumAnalyzer embeds a soft-compression amplifier model so that
get_peak_power() returns physically realistic values even though PyVISA-sim
would only give back a static placeholder.  The model parameters below define
the DUT being characterised; tweak them to explore different amplifier behaviors.
"""

from __future__ import annotations

import os
import numpy as np
import pyvisa

# ── Amplifier model parameters ──────────────────────────────────────────────
_SMALL_SIGNAL_GAIN_DB: float = 20.0   # Linear (small-signal) gain in dB
_P1DB_IN_DBM: float = 0.0             # Input-referred 1 dB compression point
_NOISE_STD_DB: float = 0.05           # Measurement noise std-dev (dB)


def _amplifier_model(pin_dbm: float) -> float:
    """
    Soft-compression amplifier model.

    Derivation of the compression coefficient b:
        Gain(Pin) = G0 - 10·log10(1 + b·10^((Pin-P1dB)/10))
    At Pin = P1dB we want Gain = G0 - 1, therefore:
        1 = 10·log10(1 + b)  →  b = 10^(1/10) - 1 ≈ 0.2589

    This gives exactly 1 dB of compression at P1dB_in and asymptotically
    approaches G0 for small signals.
    """
    b = 10.0 ** (1.0 / 10.0) - 1.0          # ≈ 0.2589
    compression = 10.0 * np.log10(
        1.0 + b * 10.0 ** ((pin_dbm - _P1DB_IN_DBM) / 10.0)
    )
    gain = _SMALL_SIGNAL_GAIN_DB - compression
    noise = np.random.normal(0.0, _NOISE_STD_DB)
    return pin_dbm + gain + noise


# ── Instrument wrappers ───────────────────────────────────────────────────────

class SignalGenerator:
    """SCPI wrapper for the simulated signal generator (GPIB::1)."""

    def __init__(self, resource: pyvisa.resources.Resource) -> None:
        self._instr = resource
        self._power_dbm: float = -30.0

    # ── Identity / reset ──────────────────────────────────────────────────
    def identify(self) -> str:
        return self._instr.query("*IDN?").strip()

    def reset(self) -> None:
        self._instr.write("*RST")
        self._instr.write("*CLS")

    # ── Frequency ─────────────────────────────────────────────────────────
    def set_frequency(self, freq_hz: float) -> None:
        self._instr.write(f":FREQ {freq_hz:.6e}")

    def get_frequency(self) -> float:
        return float(self._instr.query(":FREQ?"))

    # ── Power ─────────────────────────────────────────────────────────────
    def set_power(self, power_dbm: float) -> None:
        self._instr.write(f":POW {power_dbm:.2f}")
        self._power_dbm = power_dbm

    def get_power(self) -> float:
        return float(self._instr.query(":POW?"))

    # ── Output enable ─────────────────────────────────────────────────────
    def output_on(self) -> None:
        self._instr.write(":OUTP ON")

    def output_off(self) -> None:
        self._instr.write(":OUTP OFF")

    # ── Convenience property used by SpectrumAnalyzer ────────────────────
    @property
    def power_dbm(self) -> float:
        return self._power_dbm


class SpectrumAnalyzer:
    """
    SCPI wrapper for the simulated spectrum analyzer (GPIB::2).

    get_peak_power() sends the real SCPI query to PyVISA-sim (which returns
    a static -999.0 placeholder) and then overwrites that with an output power
    computed by the embedded amplifier model.  Call update_input_power() before
    each measurement so the model knows the current DUT drive level.
    """

    def __init__(self, resource: pyvisa.resources.Resource) -> None:
        self._instr = resource
        self._sim_input_power_dbm: float = -30.0

    # ── Identity / reset ──────────────────────────────────────────────────
    def identify(self) -> str:
        return self._instr.query("*IDN?").strip()

    def reset(self) -> None:
        self._instr.write("*RST")
        self._instr.write("*CLS")

    # ── Configuration ─────────────────────────────────────────────────────
    def set_center_frequency(self, freq_hz: float) -> None:
        self._instr.write(f":FREQ:CENT {freq_hz:.6e}")

    def set_span(self, span_hz: float) -> None:
        self._instr.write(f":FREQ:SPAN {span_hz:.6e}")

    def set_ref_level(self, ref_dbm: float) -> None:
        self._instr.write(f":DISP:WIND:TRAC:Y:RLEV {ref_dbm:.1f}")

    # ── Simulation coupling ────────────────────────────────────────────────
    def update_input_power(self, pin_dbm: float) -> None:
        """
        Inform the model of the current signal generator output level so that
        the next get_peak_power() call returns the correct compressed value.
        """
        self._sim_input_power_dbm = pin_dbm

    # ── Measurement ───────────────────────────────────────────────────────
    def get_peak_power(self) -> float:
        """
        Query peak output power (dBm).

        The SCPI transaction is sent to PyVISA-sim for protocol fidelity, but
        the returned value is discarded in favour of the amplifier model output.
        """
        self._instr.query("MEAS:POW?")   # ← real SCPI; sim returns "-999.0"
        return _amplifier_model(self._sim_input_power_dbm)


# ── Factory function ─────────────────────────────────────────────────────────

def connect_instruments(sim_yaml_path: str) -> tuple[SignalGenerator, SpectrumAnalyzer]:
    """
    Open a PyVISA-sim resource manager backed by *sim_yaml_path* and return
    a (SignalGenerator, SpectrumAnalyzer) pair ready to use.
    """
    abs_path = os.path.abspath(sim_yaml_path)
    rm = pyvisa.ResourceManager(f"{abs_path}@sim")

    def _open(address: str) -> pyvisa.resources.Resource:
        res = rm.open_resource(address)
        res.read_termination = "\n"
        res.write_termination = "\n"
        return res

    sig_gen = SignalGenerator(_open("GPIB::1::INSTR"))
    spec_an = SpectrumAnalyzer(_open("GPIB::2::INSTR"))
    return sig_gen, spec_an
