import time
from dataclasses import dataclass
from typing import Tuple

import pyCandle as pc


@dataclass
class MdState:
    pos_rad: float
    vel_rads: float
    torque_nm: float


class MabMd:
    """
    Thin wrapper around CANdle-SDK's pyCandle API.

    Important: MD must be "polled" frequently (any get/set call counts),
    otherwise its watchdog will disable output. The upstream example calls
    this out explicitly. :contentReference[oaicite:5]{index=5}
    """

    def __init__(self, md_id: int, datarate_hz: int = 1_000_000):
        if datarate_hz != 1_000_000:
            raise ValueError("For now we only wire 1M. Add enum mapping when needed.")

        self.md_id = md_id
        self.candle = pc.attachCandle(pc.CANdleDatarate_E.CAN_DATARATE_1M, pc.busTypes_t.USB)
        self.md = pc.MD(md_id, self.candle)

    def init(self, max_torque_nm: float = 0.6) -> None:
        err = self.md.init()
        if err != pc.MD_Error_t.OK:
            raise RuntimeError(f"md.init() failed: {err}")
        self.md.setMaxTorque(max_torque_nm)

    def zero(self) -> None:
        self.md.zero()

    def enable_impedance(self, kp: float = 0.0, kd: float = 0.0) -> None:
        self.md.setMotionMode(pc.MotionMode_t.IMPEDANCE)
        self.md.setImpedanceParams(kp, kd)
        self.md.enable()

    def disable(self) -> None:
        self.md.disable()

    def set_target_position(self, pos_rad: float) -> None:
        self.md.setTargetPosition(float(pos_rad))

    def read_state(self) -> MdState:
        # Use registers so we always have pos/vel/torque consistently.
        # Register names are documented in the MD register table. :contentReference[oaicite:6]{index=6}
        pos = pc.readRegisterFloat(self.md, "mainEncoderPosition")[0]
        vel = pc.readRegisterFloat(self.md, "mainEncoderVelocity")[0]
        tq = pc.readRegisterFloat(self.md, "motorTorque")[0]
        return MdState(pos_rad=float(pos), vel_rads=float(vel), torque_nm=float(tq))

    @staticmethod
    def sleep_keepalive(seconds: float, tick_hz: float = 100.0, tick_fn=None) -> None:
        """Sleep while optionally calling tick_fn to keep watchdog happy."""
        dt = 1.0 / tick_hz
        end = time.time() + seconds
        while time.time() < end:
            if tick_fn is not None:
                tick_fn()
            time.sleep(dt)