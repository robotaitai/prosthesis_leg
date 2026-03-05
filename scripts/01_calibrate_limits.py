import math
import time
from pathlib import Path

import yaml

from prosthesis_leg.mab_interface import MabMd


def load_cfg():
    return yaml.safe_load(Path("config/default.yaml").read_text())


def main():
    cfg = load_cfg()

    md = MabMd(md_id=int(cfg["md_id"]), datarate_hz=int(cfg["can_datarate"]))
    md.init(max_torque_nm=float(cfg["max_torque_nm"]))
    # kp=kd=0: actively cancels cogging so the joint is truly back-drivable by hand.
    # Target is kept at current position each tick as a watchdog keepalive.
    md.enable_impedance(kp=0.0, kd=0.0)

    print("Motor enabled (kp=kd=0) — joint is free. Move it by hand to both hard stops.")
    print("Tracking min/max encoder position. Press Ctrl+C when done.\n")

    pos_min = float("inf")
    pos_max = float("-inf")

    try:
        while True:
            st = md.read_state()
            pos = st.pos_rad
            pos_min = min(pos_min, pos)
            pos_max = max(pos_max, pos)
            md.set_target_position(pos)  # keepalive — no spring force since kp=0
            print(
                f"\rpos={pos:+8.3f} rad   min={pos_min:+8.3f}   max={pos_max:+8.3f}",
                end="",
                flush=True,
            )
            time.sleep(0.02)  # 50 Hz
    except KeyboardInterrupt:
        print("\n\nCapture complete.")
    finally:
        md.disable()

    if pos_min == float("inf") or pos_max == float("-inf"):
        print("No data captured — exiting.")
        return 1

    gear = float(cfg["gear_ratio"])
    margin_deg = float(cfg["joint_margin_deg"])
    margin_motor_rad = math.radians(margin_deg) * gear  # joint degrees → motor radians

    safe_min = pos_min + margin_motor_rad
    safe_max = pos_max - margin_motor_rad

    if safe_min >= safe_max:  # sanity: margin too large for measured range
        print(f"\nWARN: margin ({margin_deg}°) is larger than half the measured range — safe limits would be inverted.")
        print("Reduce joint_margin_deg in config/default.yaml or re-run with a wider range.")
        return 1

    print(f"\nHard stops:  min={pos_min:+.4f} rad   max={pos_max:+.4f} rad")
    print(f"Safe limits: min={safe_min:+.4f} rad   max={safe_max:+.4f} rad  (±{margin_deg}° joint margin)")

    cfg_path = Path("config/default.yaml")
    cfg["hard_min_rad"] = round(pos_min, 4)
    cfg["hard_max_rad"] = round(pos_max, 4)
    cfg["safe_min_rad"] = round(safe_min, 4)
    cfg["safe_max_rad"] = round(safe_max, 4)
    cfg_path.write_text(yaml.dump(cfg, default_flow_style=False, sort_keys=False))
    print(f"\nUpdated: {cfg_path}")

    print("\nRun these to apply limits to the drive:")
    print(f"  candletool md --id {cfg['md_id']} register write positionLimitMin {safe_min:.4f}")
    print(f"  candletool md --id {cfg['md_id']} register write positionLimitMax {safe_max:.4f}")
    print(f"  candletool md --id {cfg['md_id']} register write maxTorque {cfg['max_torque_nm']}")
    print(f"  candletool md --id {cfg['md_id']} register write maxVelocity {cfg['max_velocity_rads']}")
    print(f"  candletool md --id {cfg['md_id']} save")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
