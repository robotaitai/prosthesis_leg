import argparse
import time
from pathlib import Path

import yaml

from prosthesis_leg.mab_interface import MabMd


def load_cfg():
    return yaml.safe_load(Path("config/default.yaml").read_text())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", type=int, default=100)
    ap.add_argument("--seconds", type=float, default=None,
                    help="Duration [s]. Defaults to smoke_duration_s from config.")
    ap.add_argument("--enable", action="store_true", help="Actually enable the drive.")
    args = ap.parse_args()

    cfg = load_cfg()

    # Require calibration before running
    if cfg.get("safe_min_rad") is None or cfg.get("safe_max_rad") is None:
        print("ERROR: safe limits not set. Run 01_calibrate_limits.py first.")
        return 1

    kp = float(cfg["imp_kp"])
    kd = float(cfg["imp_kd"])
    safe_min = float(cfg["safe_min_rad"])
    safe_max = float(cfg["safe_max_rad"])
    duration = args.seconds if args.seconds is not None else float(cfg.get("smoke_duration_s", 5.0))

    print(f"Safe range: [{safe_min:.3f}, {safe_max:.3f}] rad  |  kp={kp}  kd={kd}  duration={duration}s")

    md = MabMd(md_id=args.id)
    md.init(max_torque_nm=float(cfg["max_torque_nm"]))

    st0 = md.read_state()
    print(f"connected. pos={st0.pos_rad:.3f} rad, vel={st0.vel_rads:.3f} rad/s, tq={st0.torque_nm:.3f} Nm")

    if st0.pos_rad < safe_min or st0.pos_rad > safe_max:
        print(f"ERROR: start position {st0.pos_rad:.3f} is outside safe range. Move joint to mid-range first.")
        return 1

    if not args.enable:
        print("not enabling (missing --enable). exiting.")
        return 0

    print(f"enabling impedance hold at pos={st0.pos_rad:.3f} rad")
    md.enable_impedance(kp=kp, kd=kd)
    try:
        target = st0.pos_rad
        t_end = time.time() + duration
        while time.time() < t_end:
            # Clamp target to safe range so the drive never commands past the limits
            target_clamped = max(safe_min, min(safe_max, target))
            md.set_target_position(target_clamped)
            st = md.read_state()
            at_min = st.pos_rad <= safe_min
            at_max = st.pos_rad >= safe_max
            limit_str = " [MIN LIMIT]" if at_min else " [MAX LIMIT]" if at_max else ""
            print(f"pos={st.pos_rad:+7.3f} vel={st.vel_rads:+6.3f} tq={st.torque_nm:+6.3f}{limit_str}")
            time.sleep(0.02)  # 50 Hz
    finally:
        md.disable()
        print("disabled")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
