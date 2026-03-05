"""
Gesture sweep — back-and-forth motion in impedance mode.

Run (dry-run, no motor output):
    python scripts/04_gesture_sweep.py --vel 5

Enable motor output:
    python scripts/04_gesture_sweep.py --vel 5 --enable

Override velocity interpretation (motor rad/s instead of joint rad/s):
    python scripts/04_gesture_sweep.py --vel 0.2 --motor-vel --enable

Override number of half-cycles and dwell:
    python scripts/04_gesture_sweep.py --vel 5 --half-cycles 6 --dwell 0.5 --enable

Override inner margin (joint degrees from safe limit):
    python scripts/04_gesture_sweep.py --vel 5 --margin-deg-joint 3.0 --enable
"""
import argparse
import math
import sys
import time
from pathlib import Path

import yaml

CFG_PATH = Path("config/default.yaml")


# ── config / limits ───────────────────────────────────────────────────────────

def load_cfg() -> dict:
    return yaml.safe_load(CFG_PATH.read_text())


def load_limits(cfg: dict) -> tuple[float, float]:
    """Return (safe_min_motor_rad, safe_max_motor_rad) from config. Exits if missing."""
    safe_min = cfg.get("safe_min_rad")
    safe_max = cfg.get("safe_max_rad")
    if safe_min is None or safe_max is None:
        print("ERROR: safe limits not found in config/default.yaml.")
        print("       Run  python scripts/01_calibrate_limits.py  first.")
        sys.exit(1)
    return float(safe_min), float(safe_max)


# ── argument parsing ──────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description="Back-and-forth sweep in impedance mode.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    ap.add_argument(
        "--vel", type=float, default=None,
        help="Sweep velocity. Joint rad/s by default (see --motor-vel).",
    )
    ap.add_argument(
        "--motor-vel", action="store_true",
        help="Interpret --vel as motor rad/s instead of joint rad/s.",
    )
    ap.add_argument(
        "--half-cycles", type=int, default=4,
        help="Number of half-cycles (each half = one direction traversal).",
    )
    ap.add_argument(
        "--dwell", type=float, default=0.2,
        help="Pause at each endpoint [s].",
    )
    ap.add_argument(
        "--margin-deg-joint", type=float, default=None,
        help="Inner margin from safe limits [joint degrees]. Overrides config.",
    )
    ap.add_argument(
        "--enable", action="store_true",
        help="Actually enable the drive. Without this flag the script is a dry-run.",
    )
    ap.add_argument(
        "--id", type=int, default=None,
        help="CAN drive ID. Overrides config md_id.",
    )
    return ap.parse_args()


# ── motion helpers ────────────────────────────────────────────────────────────

def ramp_to(md, target: float, motor_vel: float, dt: float,
            target_min: float, target_max: float,
            safe_min: float, safe_max: float,
            max_torque_nm: float, log_hz: float, enabled: bool) -> bool:
    """
    Move current commanded position toward `target` at `motor_vel` rad/s.
    Returns True on success, False if a safety trip occurred.
    """
    sign = 1.0 if target > 0 else -1.0  # determined from first read
    SAFETY_MARGIN_RAD = 0.2
    TORQUE_TRIP = max_torque_nm * 1.5

    log_interval = 1.0 / log_hz
    last_log = 0.0
    last_t = time.perf_counter()

    # Read actual position as starting commanded pos
    if enabled:
        st = md.read_state()
        cmd = st.pos_rad
    else:
        cmd = (target_min + target_max) / 2.0  # midpoint placeholder

    sign = 1.0 if target > cmd else -1.0

    while True:
        now = time.perf_counter()
        dt_actual = now - last_t
        last_t = now

        cmd += sign * motor_vel * dt_actual
        cmd = max(target_min, min(target_max, cmd))

        if enabled:
            md.set_target_position(cmd)
            st = md.read_state()

            # Safety: position out of bounds
            if st.pos_rad < safe_min - SAFETY_MARGIN_RAD or st.pos_rad > safe_max + SAFETY_MARGIN_RAD:
                print(f"\n[SAFETY] Position {st.pos_rad:.3f} out of safe range! Disabling.")
                return False

            # Safety: torque over-limit
            if abs(st.torque_nm) > TORQUE_TRIP:
                print(f"\n[SAFETY] Torque {st.torque_nm:.3f} Nm exceeds trip limit ({TORQUE_TRIP:.3f} Nm)! Disabling.")
                return False

            # Periodic log
            if now - last_log >= log_interval:
                last_log = now
                print(
                    f"  cmd={cmd:+7.3f}  pos={st.pos_rad:+7.3f}  "
                    f"vel={st.vel_rads:+6.3f}  tq={st.torque_nm:+6.3f} Nm"
                )
        else:
            if now - last_log >= log_interval:
                last_log = now
                print(f"  [dry-run] cmd={cmd:+7.3f}")

        # Reached target?
        if (sign > 0 and cmd >= target) or (sign < 0 and cmd <= target):
            break

        remaining = abs(target - cmd) / motor_vel
        time.sleep(min(1.0 / 100.0, remaining * 0.5))

    return True


# ── main ──────────────────────────────────────────────────────────────────────

def main() -> int:
    args = parse_args()
    cfg = load_cfg()
    safe_min, safe_max = load_limits(cfg)

    md_id      = args.id if args.id is not None else int(cfg["md_id"])
    gear       = float(cfg.get("gear_ratio", 27.0))
    loop_hz    = float(cfg.get("loop_hz", 100.0))
    max_torque = float(cfg.get("max_torque_nm", 0.6))
    kp         = float(cfg.get("imp_kp", 1.5))
    kd         = float(cfg.get("imp_kd", 0.08))

    # Inner margin
    margin_deg = args.margin_deg_joint if args.margin_deg_joint is not None \
                 else float(cfg.get("joint_margin_deg", 5.0))
    margin_motor = math.radians(margin_deg) * gear

    target_min = safe_min + margin_motor
    target_max = safe_max - margin_motor
    if target_min >= target_max:
        print(f"ERROR: inner margin ({margin_deg}°) leaves no usable range between targets.")
        print(f"       target_min={target_min:.3f}  target_max={target_max:.3f}")
        print("       Reduce --margin-deg-joint or re-calibrate with a wider range.")
        return 1

    # Velocity
    if args.vel is None:
        try:
            raw = input("Enter desired velocity [joint rad/s]: ").strip()
            joint_vel = float(raw)
        except (ValueError, EOFError):
            print("Invalid velocity.")
            return 1
    else:
        joint_vel = args.vel

    if args.motor_vel:
        motor_vel = joint_vel
        joint_vel = motor_vel / gear
    else:
        motor_vel = joint_vel * gear

    dt = 1.0 / loop_hz

    # ── header ──
    sep = "─" * 60
    print(sep)
    print(f"  Gesture sweep   drive={md_id}   {'ENABLED' if args.enable else 'DRY-RUN (no --enable)'}")
    print(sep)
    print(f"  gear_ratio      : {gear}")
    print(f"  loop_hz         : {loop_hz}")
    print(f"  kp / kd         : {kp} / {kd}")
    print(f"  max_torque_nm   : {max_torque}")
    print(f"  safe limits     : [{safe_min:.3f},  {safe_max:.3f}] motor rad")
    print(f"  inner margin    : {margin_deg}° joint  =  {margin_motor:.3f} motor rad")
    print(f"  sweep targets   : [{target_min:.3f},  {target_max:.3f}] motor rad")
    print(f"  velocity (joint): {joint_vel:.4f} rad/s  =  {math.degrees(joint_vel):.2f}°/s")
    print(f"  velocity (motor): {motor_vel:.4f} rad/s")
    print(f"  half-cycles     : {args.half_cycles}")
    print(f"  dwell           : {args.dwell} s")
    print(sep)

    if not args.enable:
        print("  [dry-run] Pass --enable to energise the drive.\n")

    from prosthesis_leg.mab_interface import MabMd
    md = MabMd(md_id=md_id)
    md.init(max_torque_nm=max_torque)

    if args.enable:
        st0 = md.read_state()
        print(f"  start pos = {st0.pos_rad:+.3f} rad\n")

        if st0.pos_rad < safe_min or st0.pos_rad > safe_max:
            print(f"ERROR: start position {st0.pos_rad:.3f} is outside safe range.")
            print("       Run reposition step in the wizard first.")
            return 1

        md.enable_impedance(kp=kp, kd=kd)

    ok = True
    try:
        # First half always goes toward target_max
        direction = 1  # +1 → toward target_max, -1 → toward target_min
        for half in range(args.half_cycles):
            target = target_max if direction > 0 else target_min
            label  = "→ max" if direction > 0 else "← min"
            print(f"  half-cycle {half+1}/{args.half_cycles}  {label}  target={target:+.3f}")

            ok = ramp_to(
                md, target, motor_vel, dt,
                target_min, target_max,
                safe_min, safe_max,
                max_torque, log_hz=10.0, enabled=args.enable,
            )
            if not ok:
                break

            if args.dwell > 0:
                print(f"  dwell {args.dwell}s at {target:+.3f}")
                t_dwell = time.time() + args.dwell
                while time.time() < t_dwell:
                    if args.enable:
                        md.set_target_position(target)
                        md.read_state()  # keepalive
                    time.sleep(dt)

            direction *= -1

    finally:
        md.disable()
        print("\n  Motor disabled.")

    if ok:
        print("  Sweep complete.")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
