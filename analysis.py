"""
analysis.py — Detect the 1 dB gain compression point (P1dB) from sweep data.

Algorithm
---------
1. Compute the small-signal gain baseline by averaging the first
   *num_linear_points* measurements (assumed to be deep in the linear regime).
2. Calculate the compression at each point: compression = baseline - measured_gain.
3. The P1dB is the input power where compression first reaches 1 dB.
4. Sub-step precision is obtained by linear interpolation between the last
   uncompressed point and the first compressed point.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np

from sweep import SweepResult


@dataclass
class CompressionResult:
    """Results from a P1dB analysis."""
    p1db_in_dbm: float       # Input power at 1 dB compression (dBm)
    p1db_out_dbm: float      # Output power at 1 dB compression (dBm)
    baseline_gain_db: float  # Small-signal linear gain (dB)
    compression_db: np.ndarray  # Compression profile across the sweep (dB)


def linear_baseline(gain_db: np.ndarray, num_points: int = 5) -> float:
    """Return the mean gain over the first *num_points* (linear-regime) points."""
    if len(gain_db) < num_points:
        raise ValueError(
            f"Need at least {num_points} sweep points to establish a baseline; "
            f"got {len(gain_db)}."
        )
    return float(np.mean(gain_db[:num_points]))


def find_p1db(
    result: SweepResult,
    num_linear_points: int = 5,
) -> Optional[CompressionResult]:
    """
    Detect the 1 dB gain compression point from a SweepResult.

    Returns None if the 1 dB compression boundary is not crossed within the
    measured sweep range (e.g. the amplifier never saturates hard enough, or
    the sweep doesn't go high enough in power).

    Parameters
    ----------
    result            : completed SweepResult from sweep.run_sweep()
    num_linear_points : how many leading points to average for the baseline
    """
    pin = result.pin_dbm
    pout = result.pout_dbm
    gain = result.gain_db

    if len(gain) < num_linear_points + 1:
        return None

    baseline = linear_baseline(gain, num_linear_points)
    compression = baseline - gain   # positive = more compressed

    # Find the first index where compression crosses 1 dB
    compressed_mask = compression >= 1.0
    indices = np.where(compressed_mask)[0]
    if len(indices) == 0:
        return None

    idx = int(indices[0])

    # ── Sub-step interpolation ────────────────────────────────────────────
    if idx > 0:
        # Linear interpolation between (idx-1) and idx to find exactly 1 dB
        c0, c1 = float(compression[idx - 1]), float(compression[idx])
        p0, p1 = float(pin[idx - 1]), float(pin[idx])
        # Fraction t along [p0, p1] where compression = 1.0
        t = (1.0 - c0) / (c1 - c0)
        p1db_in = p0 + t * (p1 - p0)
        p1db_out = float(np.interp(p1db_in, pin, pout))
    else:
        p1db_in = float(pin[idx])
        p1db_out = float(pout[idx])

    return CompressionResult(
        p1db_in_dbm=p1db_in,
        p1db_out_dbm=p1db_out,
        baseline_gain_db=baseline,
        compression_db=compression,
    )
