# Prosthesis Leg — MAB MD Drive Control

Python control stack for a prosthetic **hip joint** powered by a **MAB Robotics MD** drive
connected via a **CANdle USB** adapter.

---

## Hardware

| Component | Notes |
|-----------|-------|
| MAB Robotics MD drive | CAN ID 100 (default) |
| CANdle USB adapter | appears as `/dev/ttyACM0` |
| Gear ratio | 27 : 1 |
| Joint | Hip flexion / extension |
| Host | Raspberry Pi 4/5 or any Linux PC |

---

## Quick start (Raspberry Pi or Linux)

```bash
# 1. Clone
git clone git@github.com:robotaitai/prosthesis_leg.git
cd prosthesis_leg

# 2. Install everything (venv + Python deps + USB permissions)
make install

# 3. Log out and back in so the dialout group change takes effect
#    (or reboot the Pi)

# 4. Plug in the CANdle USB adapter, power the drive, then launch the wizard
make wizard
```

That's it. The wizard guides you through every step in order.

---

## Manual setup (if you prefer not to use Make)

```bash
python3 -m venv venv
source venv/bin/activate
pip install -e .
sudo usermod -aG dialout $USER   # then log out / reboot
sudo apt install setserial       # optional — reduces USB latency warnings
python scripts/00_wizard.py
```

---

## Wizard workflow

```
 ○  1. Calibrate limits        Motor loosened (kp=kd=0). Move hip to both
                               hard stops by hand, Ctrl+C when done.
                               → writes hard_min/max and safe_min/max to config.

 ○  2. Reposition joint        If hip is outside the safe range after power-on,
                               this loosens the motor so you can push it back.

 ○  3. Smoke impedance hold    Holds current position with a spring feel.
                               Tune imp_kp / imp_kd in config/default.yaml.

 ○  4. Gesture sweep           Constant-velocity back-and-forth ramp, N cycles.
                               Prompts for peak velocity [joint rad/s].

 ○  5. Gesture sine            Smooth sinusoidal oscillation until Ctrl+C.
                               Prompts for peak velocity [joint rad/s].

 ○  6. Gesture gait            Human hip gait pattern — heel-strike → push-off
                               → swing, repeating until Ctrl+C.
```

Steps are locked until their prerequisites are satisfied.  
Press **r** in the wizard to refresh the live position readout.  
Press **q** or Esc to quit.

---

## Scripts (run directly, bypassing the wizard)

| Script | Purpose |
|--------|---------|
| `scripts/00_wizard.py` | Curses step-by-step wizard |
| `scripts/01_calibrate_limits.py` | Passive limit capture — move hip by hand |
| `scripts/02_smoke_impedance_hold.py` | Impedance spring hold at current position |
| `scripts/04_gesture_sweep.py` | Constant-velocity back-and-forth sweep |
| `scripts/05_gesture_sine.py` | Continuous sine-wave oscillation |
| `scripts/06_gesture_gait.py` | Human hip gait motion profile |

All scripts accept `--help` for the full argument list.

### Example commands

```bash
# Calibrate (kp=kd=0, move hip to both hard stops by hand, Ctrl+C when done)
python scripts/01_calibrate_limits.py

# Smoke test — hold position for 5 seconds (duration set in config)
python scripts/02_smoke_impedance_hold.py --enable

# Dry-run sweep (no motor output) — preview trajectory before enabling
python scripts/04_gesture_sweep.py --vel 0.3

# Sweep at 0.3 joint rad/s (~17°/s), 4 half-cycles
python scripts/04_gesture_sweep.py --vel 0.3 --enable

# Continuous sine at 0.5 joint rad/s peak, until Ctrl+C
python scripts/05_gesture_sine.py --vel 0.5 --enable

# Simple rocking test — confirms motor moves before running gait
python scripts/06_gesture_gait.py --profile rock --enable

# Hip gait at slow cadence (1.5 s/stride) — default
python scripts/06_gesture_gait.py --enable

# Hip gait at normal walking speed (1.1 s/stride ≈ 54 strides/min)
python scripts/06_gesture_gait.py --stride 1.1 --enable

# Knee profile, run exactly 10 strides then stop
python scripts/06_gesture_gait.py --profile knee --strides 10 --enable
```

> **Velocity note:** `--vel` is in **joint rad/s**.  
> With gear ratio 27 and the typical ~24° total hip range, `--vel 0.3` sweeps
> end-to-end in ~4 s; `--vel 1.0` takes ~1 s.  
> Use `--motor-vel` to specify motor-side rad/s instead.

---

## Configuration — `config/default.yaml`

```yaml
# ── Drive ─────────────────────────────────────────────────────────────────────
md_id: 100
can_datarate: 1000000   # 1 Mbit/s
gear_ratio: 27.0

# ── Control loop ──────────────────────────────────────────────────────────────
loop_hz: 100

# ── Impedance gains (motor-side) ──────────────────────────────────────────────
# Joint stiffness = imp_kp × gear_ratio² = imp_kp × 729  [Nm/rad]
imp_kp: 0.5             # start here; increase if motor doesn't move
imp_kd: 0.02
smoke_duration_s: 5.0   # how long the smoke impedance hold runs [seconds]

# ── Safety limits ─────────────────────────────────────────────────────────────
max_torque_nm: 0.6
max_velocity_rads: 6.0

# ── Calibration — written automatically by 01_calibrate_limits.py ─────────────
joint_margin_deg: 5.0   # inward safety margin from each hard stop [joint °]
hard_min_rad: ...       # measured hard stop (motor rad, relative to power-on zero)
hard_max_rad: ...
safe_min_rad: ...       # hard stop ± margin
safe_max_rad: ...
```

**Tuning `imp_kp`:** joint stiffness = `imp_kp × 729` Nm/rad.
- `0.1` → very soft (~73 Nm/rad) — barely moves against gravity  
- `0.5` → moderate (~365 Nm/rad) — good starting point for a hip  
- `1.0+` → stiff — use with care, monitor torque output

---

## Gait profiles

`06_gesture_gait.py` ships three profiles selectable with `--profile`:

| Profile | Description |
|---------|-------------|
| `hip` *(default)* | Human hip flexion/extension: heel-strike → mid-stance neutral → push-off extension → swing flexion |
| `ankle` | Ankle dorsiflexion/plantarflexion: loading → mid-stance → push-off → swing clearance |
| `rock` | Simple symmetric rocking — use first to confirm the motor moves visually |

All profiles use cosine interpolation between waypoints for smooth motion.
The amplitude (fraction of available range used) defaults to 80 % and is
adjustable with `--amplitude`.

---

## Python API

```python
from prosthesis_leg.mab_interface import MabMd, MdState

md = MabMd(md_id=100)
md.init(max_torque_nm=0.6)
md.enable_impedance(kp=0.5, kd=0.02)

state: MdState = md.read_state()   # .pos_rad  .vel_rads  .torque_nm
md.set_target_position(state.pos_rad)

md.disable()
```

---

## Firmware

The CANdle USB adapter and the MD drive have separate firmware versions.

**Flash MD drive firmware** (drive powered and connected via CANdle):
```bash
# Unzip MAB_CAN_Flasher_*.zip from the MAB downloads page, then:
./MAB_CAN_Flasher_<arch> --all --baud 1M
```

**CANdle firmware** — download from the
[MAB documentation downloads page](https://mabrobotics.github.io/MD80-x-CANdle-Documentation/Downloads/intro.html)
and flash with:
```bash
candletool candle update <file>.mab
```

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `Permission denied: /dev/ttyACM0` | Run `make usb-perms` then log out / reboot |
| `Could not execute setserial …` | `sudo apt install setserial` (harmless warning otherwise) |
| `[WARN] old CANdle firmware version` | Flash the CANdle adapter (see Firmware section) |
| Motor not back-drivable during calibration | Impedance must be **enabled** with kp=kd=0, not just powered off |
| `Safe limits inverted` error | Margin larger than half the measured range — reduce `joint_margin_deg` |
| Motor enabled but doesn't visibly move | `imp_kp` too low — increase to 0.5 or higher in config |
| Position resets to ~0 after reboot | Drive zeroes encoder on power-up — always re-run calibration after power cycle |
