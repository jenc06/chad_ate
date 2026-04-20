# ATE Power Sweep — PyVISA-sim Demo

A self-contained Python ATE (Automated Test Equipment) demo that simulates a
CW power sweep on an amplifier with **no real hardware required**.
PyVISA-sim intercepts every SCPI transaction so the code behaves exactly as it
would on a live bench.

---

## Project layout

```
ate_pyvisa_sim/
├── sim_config.yaml   PyVISA-sim instrument definitions (SigGen + SpecAn)
├── instruments.py    SCPI wrapper classes + amplifier compression model
├── sweep.py          Power sweep loop; runnable as a CLI script
├── analysis.py       1 dB compression point (P1dB) detection
├── gui.py            Tkinter GUI with embedded matplotlib plot
└── requirements.txt
```

---

## Quick start

### 1. Install dependencies

```bash
cd ate_pyvisa_sim
pip install -r requirements.txt
```

### 2. Launch the GUI

```bash
python gui.py
```

Click **Run Sweep** to execute the sweep and display the gain-vs-Pin plot with
the P1dB marker.

### 3. CLI-only mode (no GUI)

```bash
python sweep.py
```

Prints a tabulated sweep table and reports the detected P1dB values.

---

## How it works

### Simulated instruments (`sim_config.yaml`)

PyVISA-sim is loaded with a YAML config that defines two virtual GPIB devices:

| Address       | Device            |
|---------------|-------------------|
| `GPIB::1`     | Signal Generator  |
| `GPIB::2`     | Spectrum Analyzer |

Every SCPI write/query is routed to these virtual instruments instead of real
hardware.  Properties (`:POW`, `:FREQ:CENT`, …) are statefully tracked by
PyVISA-sim so read-back queries return the last programmed value.

### Amplifier compression model (`instruments.py`)

The spectrum analyzer's `get_peak_power()` applies a soft-compression model:

```
Gain(Pin) = G₀ − 10·log₁₀(1 + b·10^((Pin − P1dB_in)/10))
```

where `b = 10^(1/10) − 1 ≈ 0.2589` is derived so that the gain is exactly
**1 dB below the linear value at P1dB_in**.  Gaussian noise (σ = 0.05 dB) is
added to each reading to mimic real instrument scatter.

Default model parameters (edit at the top of `instruments.py`):

| Parameter            | Value  |
|----------------------|--------|
| Small-signal gain G₀ | 20 dB  |
| Input P1dB           | 0 dBm  |
| Noise std-dev        | 0.05 dB|

### P1dB detection (`analysis.py`)

1. Average the first 5 gain measurements as the linear baseline.
2. Walk the sweep until compression ≥ 1 dB.
3. Sub-step precision via linear interpolation between the last uncompressed
   and first compressed points.

### GUI (`gui.py`)

- Sweep parameters (start/stop/step/frequency) are editable before each run.
- The sweep runs in a background thread — the GUI stays responsive.
- The matplotlib toolbar (zoom, pan, save) is embedded below the plot.
- A pink shaded region highlights the compressed portion of the curve.

---

## Customisation tips

- **Change the amplifier** — edit `_SMALL_SIGNAL_GAIN_DB`, `_P1DB_IN_DBM`, and
  `_NOISE_STD_DB` in `instruments.py`.
- **Add a second DUT** — duplicate the `spectrum analyzer` block in
  `sim_config.yaml` and add a new `GPIB::3::INSTR` resource.
- **Real hardware** — replace `connect_instruments()` with a standard
  `pyvisa.ResourceManager()` call and swap in real VISA addresses; `sweep.py`
  and `analysis.py` need no changes.
