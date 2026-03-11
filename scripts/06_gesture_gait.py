"""
Human gait gesture — repeating prosthetic ankle/knee motion profile.

The commanded position follows a piecewise cosine-interpolated curve
that approximates a real joint angle trace from the human gait cycle
(heel-strike → loading → mid-stance → push-off → swing → heel-strike).

The profile is defined in *joint degrees* relative to a neutral angle,
scaled at runtime to fit within the available safe range.

Run (dry-run, no motor output):
    python scripts/06_gesture_gait.py

Enable motor output at normal walking cadence (~54 strides/min):
    python scripts/06_gesture_gait.py --enable

Slow cadence (1.6 s/stride):
    python scripts/06_gesture_gait.py --stride 1.6 --enable

Use 80 % of the available range:
    python scripts/06_gesture_gait.py --amplitude 0.8 --enable

Run for 10 strides then stop:
    python scripts/06_gesture_gait.py --strides 10 --enable

Press Ctrl+C to stop cleanly at any time.
"""
import argparse
import math
import sys
import time
from pathlib import Path

import yaml

CFG_PATH = Path("config/default.yaml")

# ── Gait profiles ─────────────────────────────────────────────────────────────
#
# Each profile is a list of (phase, offset_joint_deg) tuples.
#   phase         : 0.0 – 1.0 within one stride cycle
#   offset_joint_deg : angle offset from neutral [joint degrees]
#                     +ve = dorsiflexion / extension
#                     -ve = plantarflexion / flexion
#
# The profile is normalised so that max |offset| = 1.0 before being
# scaled by the chosen amplitude. Define shapes here; amplitude is set
# at runtime via --amplitude and the available safe range.

PROFILES: dict[str, list[tuple[float, float]]] = {
    # Human hip flexion/extension during normal walking (Winter 2009, simplified).
    # +1 = peak flexion (leg swinging forward)
    # -1 = peak extension (leg behind body at push-off)
    "hip": [
        (0.00,  1.00),  # heel strike — peak hip flexion (~30°)
        (0.15,  0.55),  # loading response — flexion decreasing
        (0.35,  0.0),   # mid-stance — neutral (leg under body)
        (0.52, -0.65),  # terminal stance — moving into extension
        (0.62, -1.00),  # push-off — peak hip extension (~10–15°)
        (0.73, -0.30),  # toe-off — hip starts flexing rapidly
        (0.85,  0.55),  # mid-swing — flexion building for next step
        (0.95,  0.90),  # late swing — approaching peak flexion
        (1.00,  1.00),  # heel strike again
    ],
    # Simplified ankle gait (useful if joint is ankle-side)
    "ankle": [
        (0.00,  0.0),   # heel strike
        (0.08, -0.20),  # loading — slight plantarflexion
        (0.28,  0.55),  # mid-stance — dorsiflexion
        (0.48,  1.00),  # terminal stance — peak dorsiflexion
        (0.62, -0.80),  # push-off — rapid plantarflexion
        (0.73, -0.55),  # toe-off
        (0.85,  0.15),  # swing — clearance dorsiflexion
        (1.00,  0.0),   # next heel strike
    ],
    # Simple slow rock — good for first visual check that the motor moves
    "rock": [
        (0.00,  0.0),
        (0.25,  1.00),
        (0.50,  0.0),
        (0.75, -1.00),
        (1.00,  0.0),
    ],
}

DEFAULT_PROFILE = "hip"


# ── Interpolation ─────────────────────────────────────────────────────────────

def cosine_interp(y0: float, y1: float, t: float) -> float:
    """Smooth S-curve interpolation between y0 and y1, t ∈ [0, 1]."""
    mu = (1.0 - math.cos(t * math.pi)) / 2.0
    return y0 * (1.0 - mu) + y1 * mu


def profile_value(phase: float, waypoints: list[tuple[float, float]]) -> float:
    """Return the normalised profile value [-1..1] at a given phase [0..1]."""
    phase = phase % 1.0
    for i in range(len(waypoints) - 1):
        p0, v0 = waypoints[i]
        p1, v1 = waypoints[i + 1]
        if p0 <= phase <= p1:
            t = (phase - p0) / (p1 - p0)
            return cosine_interp(v0, v1, t)
    return waypoints[-1][1]


# ── Config / limits ───────────────────────────────────────────────────────────

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


# ── Argument parsing ──────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description="Human gait gesture in impedance mode.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    ap.add_argument(
        "--profile", choices=list(PROFILES), default=DEFAULT_PROFILE,
        help="Gait profile shape.",
    )
    ap.add_argument(
        "--stride", type=float, default=1.5,
        help="Duration of one complete stride cycle [seconds]. "
             "Normal walking ≈ 1.1 s; start slow (1.5–2.0 s) to verify motion.",
    )
    ap.add_argument(
        "--amplitude", type=float, default=0.80,
        help="Fraction of the available half-range to use (0 < amp ≤ 1.0). "
             "1.0 reaches from centre to the inner safe limit.",
    )
    ap.add_argument(
        "--strides", type=int, default=0,
        help="Number of strides to run then stop. 0 = run until Ctrl+C.",
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


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> int:
    args   = parse_args()
    cfg    = load_cfg()
    safe_min, safe_max = load_limits(cfg)

    md_id      = args.id if args.id is not None else int(cfg["md_id"])
    gear       = float(cfg.get("gear_ratio", 27.0))
    loop_hz    = float(cfg.get("loop_hz", 100.0))
    max_torque = float(cfg.get("max_torque_nm", 0.6))
    kp         = float(cfg.get("imp_kp", 0.1))
    kd         = float(cfg.get("imp_kd", 0.0))

    waypoints = PROFILES[args.profile]

    # Geometry
    half_range_motor  = (safe_max - safe_min) / 2.0
    center_motor      = (safe_max + safe_min) / 2.0
    amplitude_motor   = half_range_motor * min(max(args.amplitude, 0.01), 1.0)
    amplitude_joint   = amplitude_motor / gear

    target_min = center_motor - amplitude_motor
    target_max = center_motor + amplitude_motor

    stride_s  = args.stride
    dt        = 1.0 / loop_hz
    log_dt    = 0.1           # status print every 100 ms

    # Safety
    SAFETY_POS_MARGIN = 0.2
    TORQUE_TRIP       = max_torque * 1.5

    # ── Header ──
    sep = "─" * 64
    joint_range_deg = math.degrees(amplitude_motor * 2 / gear)

    print(sep)
    print(f"  Gait gesture [{args.profile}]   drive={md_id}   "
          f"{'ENABLED' if args.enable else 'DRY-RUN (no --enable)'}")
    print(sep)
    print(f"  gear_ratio        : {gear}")
    print(f"  kp / kd           : {kp} / {kd}   "
          f"{'⚠  kp is low — increase imp_kp in config if motor does not move' if kp < 0.3 else '✓'}")
    print(f"  max_torque_nm     : {max_torque}")
    print(f"  safe limits       : [{safe_min:.3f},  {safe_max:.3f}] motor rad")
    print(f"  centre            : {center_motor:.3f} motor rad")
    print(f"  amplitude         : ±{amplitude_motor:.3f} motor rad  "
          f"= ±{math.degrees(amplitude_joint):.1f}° joint  "
          f"(total swing: {joint_range_deg:.1f}°)")
    print(f"  sweep targets     : [{target_min:.3f},  {target_max:.3f}] motor rad")
    print(f"  stride period     : {stride_s:.2f} s  ({60/stride_s:.1f} strides/min)")
    print(f"  strides           : {'∞  (Ctrl+C to stop)' if args.strides == 0 else args.strides}")
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
            print("       Run the reposition step in the wizard first.")
            return 1
        md.enable_impedance(kp=kp, kd=kd)

    # Phase-offset so the sine starts at the current measured position
    # (avoids a jerk on enable).
    if args.enable:
        st_init = md.read_state()
        start_motor = st_init.pos_rad
    else:
        start_motor = center_motor

    # Find the phase whose profile value gives the closest motor position
    # by scanning the profile at fine resolution.
    best_phase, best_dist = 0.0, float("inf")
    for i in range(200):
        ph = i / 200.0
        cmd = center_motor + amplitude_motor * profile_value(ph, waypoints)
        d = abs(cmd - start_motor)
        if d < best_dist:
            best_dist, best_phase = d, ph

    ok             = True
    stride_count   = 0
    t0             = time.perf_counter()
    last_log       = t0
    phase_offset   = best_phase   # where we enter the cycle

    print(f"  Starting at profile phase {phase_offset:.3f}  "
          f"(closest cmd = {center_motor + amplitude_motor * profile_value(phase_offset, waypoints):+.3f})\n")

    cols = ("t[s]", "stride", "phase", "cmd", "pos", "vel", "tq[Nm]")
    print(f"  {'  '.join(f'{c:>7}' for c in cols)}")
    print(f"  {'  '.join('─'*7 for _ in cols)}")

    try:
        while True:
            now     = time.perf_counter()
            elapsed = now - t0

            # Current phase in the stride cycle, offset so we start smoothly
            raw_phase    = elapsed / stride_s
            phase        = (phase_offset + raw_phase) % 1.0
            stride_count = int(raw_phase)

            # Stop after N strides if requested
            if args.strides > 0 and stride_count >= args.strides:
                print(f"\n  Completed {args.strides} stride(s).")
                break

            norm_val = profile_value(phase, waypoints)
            cmd      = center_motor + amplitude_motor * norm_val
            cmd      = max(target_min, min(target_max, cmd))   # hard clamp

            if args.enable:
                md.set_target_position(cmd)
                st = md.read_state()

                if (st.pos_rad < safe_min - SAFETY_POS_MARGIN or
                        st.pos_rad > safe_max + SAFETY_POS_MARGIN):
                    print(f"\n[SAFETY] Position {st.pos_rad:.3f} out of bounds! Disabling.")
                    ok = False
                    break

                if abs(st.torque_nm) > TORQUE_TRIP:
                    print(f"\n[SAFETY] Torque {st.torque_nm:.3f} Nm exceeds trip limit "
                          f"({TORQUE_TRIP:.3f} Nm)! Disabling.")
                    ok = False
                    break

                if now - last_log >= log_dt:
                    last_log = now
                    print(
                        f"  {elapsed:7.2f}  {stride_count:7d}  {phase:7.3f}  "
                        f"{cmd:+7.3f}  {st.pos_rad:+7.3f}  "
                        f"{st.vel_rads:+7.3f}  {st.torque_nm:+7.3f}"
                    )
            else:
                if now - last_log >= log_dt:
                    last_log = now
                    print(
                        f"  {elapsed:7.2f}  {stride_count:7d}  {phase:7.3f}  "
                        f"{cmd:+7.3f}  {'[dry]':>7}  {'':>7}  {'':>7}"
                    )

            time.sleep(dt)

    except KeyboardInterrupt:
        print("\n  Ctrl+C — stopping.")
    finally:
        md.disable()
        print("  Motor disabled.")

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
