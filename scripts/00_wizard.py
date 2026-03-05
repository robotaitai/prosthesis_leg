#!/usr/bin/env python3
"""
Prosthesis leg setup wizard.

Run from project root:
    python scripts/00_wizard.py
"""
import curses
import os
import subprocess
import sys
import time
from pathlib import Path

import yaml

CFG_PATH = Path("config/default.yaml")
PY = sys.executable

# ── config helpers ────────────────────────────────────────────────────────────

def load_cfg():
    return yaml.safe_load(CFG_PATH.read_text())


def is_calibrated(cfg):
    return cfg.get("safe_min_rad") is not None and cfg.get("safe_max_rad") is not None


def pos_in_range(pos, cfg):
    if pos is None or not is_calibrated(cfg):
        return False
    return float(cfg["safe_min_rad"]) <= pos <= float(cfg["safe_max_rad"])


# ── CAN helpers ───────────────────────────────────────────────────────────────

def _suppress_stderr():
    """Redirect fd 2 → /dev/null to silence pyCandle noise. Returns saved fd."""
    saved = os.dup(2)
    devnull = os.open(os.devnull, os.O_WRONLY)
    os.dup2(devnull, 2)
    os.close(devnull)
    return saved


def _restore_stderr(saved):
    os.dup2(saved, 2)
    os.close(saved)


def read_pos(cfg):
    """Open CAN, read position, close. Returns float or None. Suppresses pyCandle logs."""
    saved = _suppress_stderr()
    try:
        from prosthesis_leg.mab_interface import MabMd
        md = MabMd(md_id=int(cfg["md_id"]))
        md.init(max_torque_nm=float(cfg["max_torque_nm"]))
        st = md.read_state()
        pos = st.pos_rad
        md.disable()
        del md
        return pos
    except Exception:
        return None
    finally:
        _restore_stderr(saved)


# ── step actions ──────────────────────────────────────────────────────────────

def run_subprocess(stdscr, script, extra_args=None):
    """Suspend curses, run script, resume. Returns subprocess returncode."""
    curses.endwin()
    print()
    args = [PY, script] + (extra_args or [])
    try:
        ret = subprocess.run(args)
        rc = ret.returncode
    except KeyboardInterrupt:
        # Ctrl+C in child propagates here; child already handled its own cleanup
        rc = 130
    print(f"\n{'─' * 55}")
    print("  Press Enter to return to the wizard...")
    try:
        input()
    except (KeyboardInterrupt, EOFError):
        pass
    stdscr.refresh()
    return rc


def run_reposition(stdscr, cfg):
    """Inline step: loosen motor (kp=kd=0) so joint can be moved by hand into safe range."""
    curses.endwin()
    print()
    print("═" * 55)
    print("  REPOSITION — motor loosened (kp = kd = 0)")
    safe_min = float(cfg["safe_min_rad"])
    safe_max = float(cfg["safe_max_rad"])
    print(f"  Safe range: [{safe_min:.3f}  …  {safe_max:.3f}] rad")
    print("  Move joint into safe range, then press Ctrl+C.")
    print("═" * 55)
    print()

    try:
        from prosthesis_leg.mab_interface import MabMd
        md = MabMd(md_id=int(cfg["md_id"]))
        md.init(max_torque_nm=float(cfg["max_torque_nm"]))
        md.enable_impedance(kp=0.0, kd=0.0)

        try:
            while True:
                st = md.read_state()
                pos = st.pos_rad
                md.set_target_position(pos)  # keepalive; no force since kp=0
                in_r = safe_min <= pos <= safe_max
                badge = "✓ IN RANGE  — Ctrl+C to finish" if in_r else "✗ out of range"
                print(
                    f"\r  pos={pos:+8.3f} rad   [{safe_min:.3f} … {safe_max:.3f}]   {badge}      ",
                    end="", flush=True,
                )
                time.sleep(0.02)
        except KeyboardInterrupt:
            print("\n\n  Stopping reposition...")
        finally:
            md.disable()
            print("  Motor disabled.")
    except Exception as e:
        print(f"\n  Error: {e}")

    print("\n  Press Enter to return to the wizard...")
    input()
    stdscr.refresh()


# ── step definitions ──────────────────────────────────────────────────────────
#
# Each step:
#   label    – displayed name
#   desc     – one-line description shown below label
#   ready    – callable(cfg, pos) → bool  (can the user run this step now?)
#   done     – callable(cfg, pos) → bool  (is this step already completed?)
#   action   – callable(stdscr, cfg)      (what happens when Enter is pressed)

STEPS = [
    {
        "label": "Calibrate limits",
        "desc":  "Move joint by hand to both hard stops — writes safe range to config.",
        "ready": lambda cfg, pos: True,
        "done":  lambda cfg, pos: is_calibrated(cfg),
        "action": lambda stdscr, cfg: run_subprocess(stdscr, "scripts/01_calibrate_limits.py"),
    },
    {
        "label": "Reposition joint  (loosen motor)",
        "desc":  "kp=kd=0 so you can push joint back into safe range by hand.",
        "ready": lambda cfg, pos: is_calibrated(cfg),
        "done":  lambda cfg, pos: pos_in_range(pos, cfg),
        "action": lambda stdscr, cfg: run_reposition(stdscr, cfg),
    },
    {
        "label": "Smoke impedance hold",
        "desc":  "Hold position with spring feel. Requires calibration + joint in range.",
        "ready": lambda cfg, pos: is_calibrated(cfg) and pos_in_range(pos, cfg),
        "done":  lambda cfg, pos: False,
        "action": lambda stdscr, cfg: run_subprocess(
            stdscr, "scripts/02_smoke_impedance_hold.py", ["--enable"]
        ),
    },
    {
        "label": "Gesture sweep  (linear ramp, N cycles)",
        "desc":  "Back-and-forth at constant velocity. Prompts for velocity.",
        "ready": lambda cfg, pos: is_calibrated(cfg) and pos_in_range(pos, cfg),
        "done":  lambda cfg, pos: False,
        "action": lambda stdscr, cfg: run_subprocess(
            stdscr, "scripts/04_gesture_sweep.py", ["--enable"]
        ),
    },
    {
        "label": "Gesture sine   (smooth wave, until Ctrl+C)",
        "desc":  "Continuous sine oscillation. Prompts for peak velocity.",
        "ready": lambda cfg, pos: is_calibrated(cfg) and pos_in_range(pos, cfg),
        "done":  lambda cfg, pos: False,
        "action": lambda stdscr, cfg: run_subprocess(
            stdscr, "scripts/05_gesture_sine.py", ["--enable"]
        ),
    },
]

ICONS = {"done": "✓", "ready": "▶", "locked": "○"}

# ── drawing ───────────────────────────────────────────────────────────────────

TITLE = " Prosthesis Leg — Setup Wizard "

C_DONE     = 1   # green
C_SEL      = 2   # cyan highlight
C_LOCKED   = 3   # dim grey
C_WARN     = 4   # yellow
C_HEADER   = 5   # bold cyan


def draw(stdscr, sel, cfg, pos, msg):
    stdscr.erase()
    h, w = stdscr.getmaxyx()

    # ── title bar ──
    bar = TITLE.center(w)
    stdscr.attron(curses.color_pair(C_HEADER) | curses.A_BOLD)
    stdscr.addstr(0, 0, bar[:w])
    stdscr.attroff(curses.color_pair(C_HEADER) | curses.A_BOLD)

    # ── drive status ──
    calib_str = "calibrated ✓" if is_calibrated(cfg) else "NOT calibrated"
    if pos is None:
        pos_str = "pos = ---"
        range_str = ""
    else:
        pos_str = f"pos = {pos:+.3f} rad"
        if is_calibrated(cfg):
            range_str = "  ✓ in range" if pos_in_range(pos, cfg) else "  ✗ OUT OF RANGE"
        else:
            range_str = ""

    status_line = f"  Drive {cfg.get('md_id', '?')} │ {pos_str}{range_str} │ {calib_str}"
    stdscr.addstr(1, 0, "─" * w)
    stdscr.addstr(2, 0, status_line[:w])
    stdscr.addstr(3, 0, "─" * w)

    # ── steps ──
    for i, step in enumerate(STEPS):
        y = 5 + i * 3
        if y + 1 >= h - 3:
            break

        done  = step["done"](cfg, pos)
        ready = step["ready"](cfg, pos)

        if done:
            icon = ICONS["done"]
            attr = curses.color_pair(C_DONE) | curses.A_BOLD
        elif ready:
            icon = ICONS["ready"]
            attr = curses.A_BOLD
        else:
            icon = ICONS["locked"]
            attr = curses.color_pair(C_LOCKED) | curses.A_DIM

        label = f" {icon}  {i+1}. {step['label']}"

        if i == sel:
            stdscr.attron(curses.color_pair(C_SEL) | curses.A_BOLD)
            stdscr.addstr(y, 2, label.ljust(w - 4)[:w - 4])
            stdscr.attroff(curses.color_pair(C_SEL) | curses.A_BOLD)
        else:
            stdscr.attron(attr)
            stdscr.addstr(y, 2, label[:w - 4])
            stdscr.attroff(attr)

        # sub-description
        suffix = "" if ready else "   [complete previous steps first]"
        desc_attr = curses.color_pair(C_LOCKED) | curses.A_DIM
        stdscr.attron(desc_attr)
        stdscr.addstr(y + 1, 7, (step["desc"] + suffix)[:w - 8])
        stdscr.attroff(desc_attr)

    # ── footer ──
    stdscr.addstr(h - 3, 0, "─" * w)
    if msg:
        stdscr.attron(curses.color_pair(C_WARN))
        stdscr.addstr(h - 2, 0, f"  {msg}"[:w])
        stdscr.attroff(curses.color_pair(C_WARN))
    footer = "  ↑↓ navigate    Enter run step    r refresh position    q quit"
    stdscr.addstr(h - 1, 0, footer[:w])

    stdscr.refresh()


# ── main loop ─────────────────────────────────────────────────────────────────

def wizard(stdscr):
    curses.curs_set(0)
    curses.use_default_colors()
    curses.start_color()
    curses.init_pair(C_DONE,   curses.COLOR_GREEN,  -1)
    curses.init_pair(C_SEL,    curses.COLOR_BLACK,  curses.COLOR_CYAN)
    curses.init_pair(C_LOCKED, curses.COLOR_WHITE,  -1)
    curses.init_pair(C_WARN,   curses.COLOR_YELLOW, -1)
    curses.init_pair(C_HEADER, curses.COLOR_CYAN,   -1)

    stdscr.timeout(100)  # non-blocking getch, refresh ~10 Hz

    cfg = load_cfg()
    pos = read_pos(cfg)
    sel = 0
    msg = ""

    while True:
        draw(stdscr, sel, cfg, pos, msg)
        msg = ""

        key = stdscr.getch()
        if key == curses.ERR:
            continue

        if key in (ord('q'), ord('Q'), 27):
            break

        elif key == curses.KEY_UP:
            sel = (sel - 1) % len(STEPS)

        elif key == curses.KEY_DOWN:
            sel = (sel + 1) % len(STEPS)

        elif key in (ord('r'), ord('R')):
            # Pause curses only long enough to read position (output suppressed)
            cfg = load_cfg()
            pos = read_pos(cfg)
            msg = (f"Refreshed — pos={pos:+.3f} rad" if pos is not None
                   else "Could not read position (check USB/power).")

        elif key in (curses.KEY_ENTER, ord('\n'), ord('\r')):
            step = STEPS[sel]
            if not step["ready"](cfg, pos):
                msg = "⚠  Complete the previous steps first."
            else:
                step["action"](stdscr, cfg)
                cfg = load_cfg()        # reload — calibration may have updated limits
                pos = read_pos(cfg)     # refresh position after step


def main():
    curses.wrapper(wizard)


if __name__ == "__main__":
    main()
