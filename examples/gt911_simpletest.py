# SPDX-FileCopyrightText: Copyright (c) 2026 Liz Clark for Adafruit Industries
#
# SPDX-License-Identifier: MIT

import time

import board

import adafruit_gt911

i2c = board.I2C()

ts = adafruit_gt911.GT911(i2c, rotation=0)
print(f"Touch area: {ts.width} x {ts.height}")

while True:
    for point in ts.touch:
        print(f"finger {point['id']}: x={point['x']} y={point['y']}")
    time.sleep(0.05)
