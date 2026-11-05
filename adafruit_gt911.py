# SPDX-FileCopyrightText: Copyright (c) 2023 Robert Grizzell
# SPDX-FileCopyrightText: Copyright (c) 2026 Liz Clark for Adafruit Industries
#
# SPDX-License-Identifier: MIT
"""
`adafruit_gt911`
================================================================================

CircuitPython driver for the GT911 touch screen controller


* Author(s): Robert Grizzell, Liz Clark

Implementation Notes
--------------------

Based on CircuitPython_GT911 in the Community Bundle by Robert Grizzell
* https://github.com/rgrizzell/CircuitPython_GT911

**Software and Dependencies:**

* Adafruit CircuitPython firmware for the supported boards:
  https://circuitpython.org/downloads

* Adafruit's Bus Device library: https://github.com/adafruit/Adafruit_CircuitPython_BusDevice
"""

import time

from adafruit_bus_device.i2c_device import I2CDevice
from micropython import const

try:
    import busio
    from microcontroller import Pin
except ImportError:
    pass

__version__ = "0.0.0+auto.0"
__repo__ = "https://github.com/adafruit/Adafruit_CircuitPython_GT911.git"

GT911_ADDRESS = const(0x5D)
"""The default I2C address"""
GT911_ALTERNATE_ADDRESS = const(0x14)
"""The alternate I2C address, selected at reset with the interrupt pin high"""

_REG_COMMAND = const(0x8040)
_REG_X_RESOLUTION = const(0x8048)
_REG_PRODUCT_ID = const(0x8140)
_REG_STATUS = const(0x814E)
_REG_POINTS = const(0x814F)

_STATUS_READY = const(0x80)
_POINT_SIZE = const(8)
_MAX_TOUCHES = const(5)

# For each display rotation: (invert x, invert y, swap x and y), applied in
# that order to the controller's coordinates
_TRANSFORMS = {
    0: (False, False, False),
    90: (True, False, True),
    180: (True, True, False),
    270: (False, True, True),
}


class GT911:
    """Driver for the GT911 capacitive touch controller.

    :param ~busio.I2C i2c: The I2C bus the controller is connected to
    :param int address: The I2C address, `GT911_ADDRESS` (0x5D) or
        `GT911_ALTERNATE_ADDRESS` (0x14)
    :param ~microcontroller.Pin reset_pin: The controller's reset pin, if
        connected. On the Raspberry Pi Touch Display 2 the display's own
        controller handles reset, so leave this out.
    :param ~microcontroller.Pin int_pin: The controller's interrupt pin, if
        connected. With ``reset_pin``, it selects ``address`` during reset.
    :param int rotation: Report touches for a display with this rotation:
        0, 90, 180 or 270, matching ``display.rotation``
    """

    def __init__(
        self,
        i2c: busio.I2C,
        address: int = GT911_ADDRESS,
        *,
        reset_pin: Pin | None = None,
        int_pin: Pin | None = None,
        rotation: int = 0,
    ) -> None:
        if reset_pin is not None:
            self._reset(reset_pin, int_pin, address)
        self._device = I2CDevice(i2c, address)
        self._buffer = bytearray(2 + _POINT_SIZE * _MAX_TOUCHES)
        self._touches = []

        product_id = self._read(_REG_PRODUCT_ID, 4)
        if product_id[0:3] != b"911":
            raise RuntimeError("GT911 not found")
        resolution = self._read(_REG_X_RESOLUTION, 4)
        self._width = resolution[0] | (resolution[1] << 8)
        self._height = resolution[2] | (resolution[3] << 8)
        self._write(_REG_COMMAND, 0)
        self.rotation = rotation

    @staticmethod
    def _reset(reset_pin: Pin, int_pin: Pin | None, address: int) -> None:
        """Reset the controller. With the interrupt pin, also select the
        address: it is sampled when reset is released."""
        import digitalio  # noqa: PLC0415

        reset = digitalio.DigitalInOut(reset_pin)
        reset.switch_to_output(value=False)
        interrupt = None
        if int_pin is not None:
            interrupt = digitalio.DigitalInOut(int_pin)
            interrupt.switch_to_output(value=address == GT911_ALTERNATE_ADDRESS)
        time.sleep(0.01)
        reset.value = True
        time.sleep(0.005)
        if interrupt is not None:
            interrupt.value = False
            time.sleep(0.05)
            interrupt.deinit()
        reset.deinit()
        time.sleep(0.05)

    def _read(self, register: int, length: int) -> memoryview:
        buffer = self._buffer
        buffer[0] = register >> 8
        buffer[1] = register & 0xFF
        with self._device as device:
            device.write_then_readinto(buffer, buffer, out_end=2, in_start=2, in_end=2 + length)
        return memoryview(buffer)[2 : 2 + length]

    def _write(self, register: int, value: int) -> None:
        with self._device as device:
            device.write(bytes((register >> 8, register & 0xFF, value)))

    @property
    def rotation(self) -> int:
        """The display rotation touches are reported for: 0, 90, 180 or 270"""
        return self._rotation

    @rotation.setter
    def rotation(self, value: int) -> None:
        if value not in _TRANSFORMS:
            raise ValueError("rotation must be 0, 90, 180 or 270")
        self._rotation = value
        self._invert_x, self._invert_y, self._swap = _TRANSFORMS[value]

    @property
    def width(self) -> int:
        """Width of the touch area at the current rotation, in pixels"""
        return self._height if self._swap else self._width

    @property
    def height(self) -> int:
        """Height of the touch area at the current rotation, in pixels"""
        return self._width if self._swap else self._height

    def _rotate(self, x: int, y: int) -> tuple:
        if self._invert_x:
            x = self._width - 1 - x
        if self._invert_y:
            y = self._height - 1 - y
        return (y, x) if self._swap else (x, y)

    @property
    def touch(self) -> list:
        """The current touch points, up to 5, as a list of dictionaries with
        ``"x"``, ``"y"``, ``"size"`` and ``"id"`` keys. ``"id"`` stays the
        same for a finger while it is down."""
        status = self._read(_REG_STATUS, 1)[0]
        if not status & _STATUS_READY:
            return self._touches
        count = min(status & 0x0F, _MAX_TOUCHES)
        touch = []
        if count:
            data = self._read(_REG_POINTS, count * _POINT_SIZE)
            for index in range(count):
                point = data[index * _POINT_SIZE : (index + 1) * _POINT_SIZE]
                x, y = self._rotate(point[1] | (point[2] << 8), point[3] | (point[4] << 8))
                touch.append(
                    {
                        "x": x,
                        "y": y,
                        "size": point[5] | (point[6] << 8),
                        "id": point[0],
                    }
                )
        self._write(_REG_STATUS, 0)
        self._touches = touch
        return touch
