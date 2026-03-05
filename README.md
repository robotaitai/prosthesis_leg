# Prosthesis Leg — MAB MD Drive Control

Python control stack for a prosthetic leg powered by a **MAB Robotics MD** drive
connected via a **CANdle USB** adapter.

---

## Hardware

| Component | Notes |
|-----------|-------|
| MAB Robotics MD drive | CAN ID 100 (default) |
| CANdle USB adapter | appears as `/dev/ttyACM0` |
| Gear ratio | 27 : 1 |
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
 ✓  1. Calibrate limits           motor loosened (kp=kd=0), move joint to both
                                  hard stops by hand, Ctrl+C when done.
                                  → writes safe_min_rad / safe_max_rad to config

 ▶  2. Reposition joint           if joint is outside safe range, this step
                                  loosens the motor so you can push it back by hand.

 ○  3. Smoke impedance hold       holds current position with a spring feel.
                                  Tune imp_kp / imp_kd in config/default.yaml.

 ○  4. Gesture sweep              constant-velocity back-and-forth ramp, N cycles.
                                  Prompts for peak velocity [joint rad/s].

 ○  5. Gesture sine               smooth sinusoidal oscillation until Ctrl+C.
                                  Prompts for peak velocity [joint rad/s].
```

Each step is locked until its prerequisites are satisfied.  
Press **r** in the wizard to refresh the position readout.  
Press **q** or Esc to quit.

---

## Scripts (run directly, bypassing the wizard)

| Script | Purpose |
|--------|---------|
| `scripts/00_wizard.py` | Curses setup wizard |
| `scripts/01_calibrate_limits.py` | Passive limit capture — move joint by hand |
| `scripts/02_smoke_impedance_hold.py` | Impedance hold at current position |
| `scripts/04_gesture_sweep.py` | Linear ramp back-and-forth sweep |
| `scripts/05_gesture_sine.py` | Continuous sine-wave oscillation |

All scripts accept `--help` for the full argument list.

### Example commands

```bash
# Calibrate (kp=kd=0, move joint to both stops by hand, Ctrl+C when done)
python scripts/01_calibrate_limits.py

# Smoke test — hold position for 5 seconds
python scripts/02_smoke_impedance_hold.py --enable --seconds 5

# Dry-run sweep (no motor output) — preview the trajectory
python scripts/04_gesture_sweep.py --vel 0.3

# Sweep at 0.3 joint rad/s (~17°/s), 4 half-cycles
python scripts/04_gesture_sweep.py --vel 0.3 --enable

# Sweep faster, 6 half-cycles, 0.3 s dwell at each end
python scripts/04_gesture_sweep.py --vel 0.8 --half-cycles 6 --dwell 0.3 --enable

# Continuous sine at 0.5 joint rad/s peak (~29°/s), until Ctrl+C
python scripts/05_gesture_sine.py --vel 0.5 --enable
```

> **Velocity note:** `--vel` is in **joint rad/s**.  
> With gear ratio 27 and ~35° total joint range, `--vel 0.3` sweeps end-to-end
> in ~4 s; `--vel 1.0` takes ~1 s. Use `--motor-vel` to specify motor-side rad/s instead.

---

## Configuration — `config/default.yaml`

```yaml
md_id: 100              # CAN drive ID
can_datarate: 1000000   # 1 Mbit/s
gear_ratio: 27.0

loop_hz: 100            # control loop rate
joint_margin_deg: 5.0   # safety margin inward from each hard stop

# Filled in automatically by 01_calibrate_limits.py:
hard_min_rad: -21.07    # measured hard stop (motor rad)
hard_max_rad: -0.05
safe_min_rad: -18.72    # hard stop + margin
safe_max_rad: -2.41

max_torque_nm: 0.6      # hard torque cap sent to drive
max_velocity_rads: 6.0

# Impedance gains (motor-side) — tune these for desired spring feel:
imp_kp: 0.1             # stiffness  [Nm / motor_rad]
imp_kd: 0.01            # damping    [Nm·s / motor_rad]
```

Joint-side stiffness = `imp_kp × gear²` = `imp_kp × 729` Nm/rad.  
Start low (0.05–0.2) and increase gradually.

---

## Python API

```python
from prosthesis_leg.mab_interface import MabMd, MdState

md = MabMd(md_id=100)
md.init(max_torque_nm=0.6)
md.enable_impedance(kp=0.1, kd=0.01)

state: MdState = md.read_state()   # .pos_rad  .vel_rads  .torque_nm
md.set_target_position(state.pos_rad)

md.disable()
```

---

## Firmware

The CANdle USB adapter and the MD drive have separate firmware versions.

**Flash MD drive firmware** (run from host PC, drive powered and connected):
```bash
# Find the flasher in the MAB_CAN_Flasher_*.zip from MAB downloads page
./MAB_CAN_Flasher_<arch> --all --baud 1M
```

**CANdle firmware** — download from the
[MAB documentation downloads page](https://mabrobotics.github.io/MD80-x-CANdle-Documentation/Downloads/intro.html)
and flash with `candletool candle update <file>.mab`.

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `Permission denied: /dev/ttyACM0` | Run `make usb-perms` then log out / reboot |
| `Could not execute setserial …` | `sudo apt install setserial` (harmless warning otherwise) |
| `[WARN] old CANdle firmware version` | Flash the CANdle adapter (see Firmware section above) |
| Motor not back-drivable during calibration | Impedance must be **enabled** with kp=kd=0, not just disabled |
| `Safe limits inverted` error | Joint range too small for margin — reduce `joint_margin_deg` in config |
| Position reads ~0 after reboot | Drive zeroes on power-up; re-run calibration or note that limits are relative to power-on position |
