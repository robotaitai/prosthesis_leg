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
git clone <repo-url> prosthesis_leg
cd prosthesis_leg

# 2. Install everything (venv + Python deps + USB permissions)
make install

# 3. Log out and back in so the dialout group change takes effect
#    (or reboot the Pi)

# 4. Launch the wizard
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

## Wizard steps

```
 ✓  1. Calibrate limits          — move joint to both hard stops by hand
 ▶  2. Reposition joint          — loosen motor to move joint back in range
 ○  3. Smoke impedance hold      — feel the spring holding at current pos
 ○  4. Gesture sweep             — constant-velocity back-and-forth, N cycles
 ○  5. Gesture sine              — smooth sinusoidal sweep until Ctrl+C
```

Steps are locked until their prerequisites are complete.

---

## Scripts (can also be run directly)

| Script | Purpose |
|--------|---------|
| `scripts/00_wizard.py` | Interactive curses wizard |
| `scripts/01_calibrate_limits.py` | Read hard stops, write safe limits to config |
| `scripts/02_smoke_impedance_hold.py` | Hold position with tunable spring |
| `scripts/04_gesture_sweep.py` | Linear ramp sweep |
| `scripts/05_gesture_sine.py` | Sine-wave sweep |

### Examples

```bash
# Calibrate (motor loosened, move by hand, Ctrl+C when done)
python scripts/01_calibrate_limits.py

# Smoke test — feel the impedance spring (3 seconds)
python scripts/02_smoke_impedance_hold.py --enable --seconds 3

# Sweep at 5 joint°/s, 4 half-cycles
python scripts/04_gesture_sweep.py --vel 5 --enable

# Continuous sine at 8 joint°/s peak, until Ctrl+C
python scripts/05_gesture_sine.py --vel 8 --enable
```

All scripts accept `--help` for full argument reference.

---

## Configuration — `config/default.yaml`

```yaml
md_id: 100           # CAN drive ID
can_datarate: 1000000
gear_ratio: 27.0

joint_margin_deg: 5.0   # safety margin inside hard stops

# Written by calibration script:
safe_min_rad: null
safe_max_rad: null

max_torque_nm: 0.6
max_velocity_rads: 6.0

# Impedance gains (motor-side) — tune here:
imp_kp: 0.4
imp_kd: 0.005
```

---

## Python package

The `src/prosthesis_leg/` package exposes:

```python
from prosthesis_leg.mab_interface import MabMd, MdState

md = MabMd(md_id=100)
md.init(max_torque_nm=0.6)
md.enable_impedance(kp=0.4, kd=0.005)

state = md.read_state()   # → MdState(pos_rad, vel_rads, torque_nm)
md.set_target_position(state.pos_rad)

md.disable()
```

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `Permission denied: /dev/ttyACM0` | Run `make usb-perms`, then log out/reboot |
| `Could not execute command 'setserial …'` | `sudo apt install setserial` (harmless warning otherwise) |
| `[WARN] old CANdle firmware` | Flash CANdle firmware from [MAB downloads](https://mabrobotics.github.io/MD80-x-CANdle-Documentation/Downloads/intro.html) |
| Motor not back-drivable in calibration | Ensure impedance is enabled (kp=kd=0), not just disabled |
| Safe limits inverted after calibration | Range too small vs. margin — reduce `joint_margin_deg` in config |
