"""
Sine-wave gesture — continuous smooth oscillation in impedance mode.

The commanded position follows:
    cmd(t) = center + amplitude * sin(2π * f * t + phase)

where amplitude = (target_max - target_min) / 2  (motor rad)
and   frequency f is derived from the desired peak velocity:
    f = peak_motor_vel / (2π * amplitude)

Run (dry-run, no motor output):
    python scripts/05_gesture_sine.py --vel 5

Enable motor output:
    python scripts/05_gesture_sine.py --vel 5 --enable

Motor rad/s instead of joint rad/s:
    python scripts/05_gesture_sine.py --vel 0.2 --motor-vel --enable

Override inner margin and start phase:
    python scripts/05_gesture_sine.py --vel 5 --margin-deg-joint 3.0 --enable

Press Ctrl+C to stop cleanly.
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
        description="Continuous sine-wave oscillation in impedance mode.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    ap.add_argument(
        "--vel", type=float, default=None,
        help="Desired PEAK velocity. Joint rad/s by default (see --motor-vel).",
    )
    ap.add_argument(
        "--motor-vel", action="store_true",
        help="Interpret --vel as motor rad/s instead of joint rad/s.",
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


# ── main ──────────────────────────────────────────────────────────────────────

def main() -> int:
    args = parse_args()
    cfg  = load_cfg()
    safe_min, safe_max = load_limits(cfg)

    md_id      = args.id if args.id is not None else int(cfg["md_id"])
    gear       = float(cfg.get("gear_ratio", 27.0))
    loop_hz    = float(cfg.get("loop_hz", 100.0))
    max_torque = float(cfg.get("max_torque_nm", 0.6))
    kp         = float(cfg.get("imp_kp", 1.5))
    kd         = float(cfg.get("imp_kd", 0.08))

    # Inner margin (same convention as sweep script)
    margin_deg   = args.margin_deg_joint if args.margin_deg_joint is not None \
                   else float(cfg.get("joint_margin_deg", 5.0))
    margin_motor = math.radians(margin_deg) * gear

    target_min = safe_min + margin_motor
    target_max = safe_max - margin_motor
    if target_min >= target_max:
        print(f"ERROR: inner margin ({margin_deg}°) leaves no usable range.")
        print(f"       target_min={target_min:.3f}  target_max={target_max:.3f}")
        print("       Reduce --margin-deg-joint or re-calibrate with a wider range.")
        return 1

    center    = (target_min + target_max) / 2.0
    amplitude = (target_max - target_min) / 2.0   # motor rad

    # Velocity
    if args.vel is None:
        try:
            raw = input("Enter desired peak velocity [joint rad/s]: ").strip()
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

    # Frequency derived from peak velocity:  v_peak = A * 2π * f  → f = v_peak / (A * 2π)
    frequency = motor_vel / (2.0 * math.pi * amplitude)
    period    = 1.0 / frequency

    # Safety
    SAFETY_POS_MARGIN = 0.2   # rad beyond safe limit before trip
    TORQUE_TRIP       = max_torque * 1.5

    dt         = 1.0 / loop_hz
    log_period = 0.1   # 10 Hz status print

    # ── header ──
    sep = "─" * 62
    print(sep)
    print(f"  Sine-wave gesture   drive={md_id}   "
          f"{'ENABLED' if args.enable else 'DRY-RUN (no --enable)'}")
    print(sep)
    print(f"  gear_ratio        : {gear}")
    print(f"  loop_hz           : {loop_hz}")
    print(f"  kp / kd           : {kp} / {kd}")
    print(f"  max_torque_nm     : {max_torque}")
    print(f"  safe limits       : [{safe_min:.3f},  {safe_max:.3f}] motor rad")
    print(f"  sweep targets     : [{target_min:.3f},  {target_max:.3f}] motor rad")
    print(f"  center / amplitude: {center:.3f} / ±{amplitude:.3f} motor rad")
    print(f"  peak vel (joint)  : {joint_vel:.4f} rad/s  =  {math.degrees(joint_vel):.2f}°/s")
    print(f"  peak vel (motor)  : {motor_vel:.4f} rad/s")
    print(f"  frequency         : {frequency:.4f} Hz   period: {period:.3f} s")
    print(sep)
    print("  Press Ctrl+C to stop.\n")

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
        # Phase offset so the sine starts at the current actual position
        # rather than jumping to center.
        if args.enable:
            st_init = md.read_state()
            start_pos = st_init.pos_rad
        else:
            start_pos = center

        # Clamp start_pos into [-1, 1] range for asin
        ratio = max(-1.0, min(1.0, (start_pos - center) / amplitude))
        phase = math.asin(ratio)   # rad; starts sine at current position

        t0       = time.perf_counter()
        last_log = t0

        while True:
            t_now = time.perf_counter()
            elapsed = t_now - t0

            cmd = center + amplitude * math.sin(2.0 * math.pi * frequency * elapsed + phase)
            cmd = max(target_min, min(target_max, cmd))   # hard clamp

            if args.enable:
                md.set_target_position(cmd)
                st = md.read_state()

                # Safety: position
                if (st.pos_rad < safe_min - SAFETY_POS_MARGIN or
                        st.pos_rad > safe_max + SAFETY_POS_MARGIN):
                    print(f"\n[SAFETY] Position {st.pos_rad:.3f} out of bounds! Disabling.")
                    ok = False
                    break

                # Safety: torque
                if abs(st.torque_nm) > TORQUE_TRIP:
                    print(f"\n[SAFETY] Torque {st.torque_nm:.3f} Nm exceeds trip limit "
                          f"({TORQUE_TRIP:.3f} Nm)! Disabling.")
                    ok = False
                    break

                if t_now - last_log >= log_period:
                    last_log = t_now
                    cycle = elapsed * frequency
                    print(
                        f"  t={elapsed:6.2f}s  cycle={cycle:5.2f}  "
                        f"cmd={cmd:+7.3f}  pos={st.pos_rad:+7.3f}  "
                        f"vel={st.vel_rads:+6.3f}  tq={st.torque_nm:+6.3f} Nm"
                    )
            else:
                if t_now - last_log >= log_period:
                    last_log = t_now
                    cycle = elapsed * frequency
                    print(f"  [dry-run] t={elapsed:6.2f}s  cycle={cycle:5.2f}  cmd={cmd:+7.3f}")

            time.sleep(dt)

    except KeyboardInterrupt:
        print("\n  Ctrl+C — stopping.")
    finally:
        md.disable()
        print("  Motor disabled.")

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
