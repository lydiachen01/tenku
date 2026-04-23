# epaper4in2v2.py — MicroPython driver for Waveshare 4.2" e-Paper V2
# 400x300 pixels, SSD1683 controller
from micropython import const
from time import sleep_ms

EPD_WIDTH  = const(400)
EPD_HEIGHT = const(300)

# Partial update LUT for SSD1683 (from Waveshare official V2 source)
# 5 tables x 7 bytes = 35 bytes (voltage levels per transition type)
# followed by 7 timing periods x 5 bytes = 35 bytes
# total 70 bytes sent to register 0x32
LUT_PARTIAL = bytearray([
    # Voltage level selection for each transition (7 bytes each):
    # BB (black stays black): no drive needed
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    # BW (black to white): positive drive
    0x80, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    # WB (white to black): negative drive
    0x40, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    # WW (white stays white): no drive needed
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    # VCOM: no change
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    # Timing periods (TP A, B, C, D, repeat count) x 7 periods:
    0x0A, 0x00, 0x00, 0x00, 0x00,   # Period 0: drive for 10 frames
    0x00, 0x00, 0x00, 0x00, 0x00,   # Period 1: off
    0x00, 0x00, 0x00, 0x00, 0x00,   # Period 2: off
    0x00, 0x00, 0x00, 0x00, 0x00,   # Period 3: off
    0x00, 0x00, 0x00, 0x00, 0x00,   # Period 4: off
    0x00, 0x00, 0x00, 0x00, 0x00,   # Period 5: off
    0x00, 0x00, 0x00, 0x00, 0x00,   # Period 6: off
])

class EPD:
    def __init__(self, spi, cs, dc, rst, busy):
        self.spi = spi
        self.cs = cs
        self.dc = dc
        self.rst = rst
        self.busy = busy
        self.width = EPD_WIDTH
        self.height = EPD_HEIGHT
        self.cs.init(self.cs.OUT, value=1)
        self.dc.init(self.dc.OUT, value=0)
        self.rst.init(self.rst.OUT, value=0)
        self.busy.init(self.busy.IN)
        self._prev_buf = None

    def _command(self, command, data=None):
        self.dc(0)
        self.cs(0)
        self.spi.write(bytearray([command]))
        self.cs(1)
        if data is not None:
            self._data(data)

    def _data(self, data):
        self.dc(1)
        self.cs(0)
        if isinstance(data, int):
            self.spi.write(bytearray([data]))
        else:
            self.spi.write(data)
        self.cs(1)

    def wait_until_idle(self):
        while self.busy.value() == 1:   # SSD1683: HIGH = busy
            sleep_ms(10)

    def reset(self):
        self.rst(1); sleep_ms(20)
        self.rst(0); sleep_ms(2)
        self.rst(1); sleep_ms(20)

    def init(self):
        self.reset()
        self.wait_until_idle()
        self._command(0x12)             # SW_RESET
        self.wait_until_idle()
        self._command(0x21, b'\x40\x00')
        self._command(0x3C, b'\x05')    # Border waveform (full refresh)
        self._command(0x11, b'\x03')    # Data entry mode
        self._command(0x01, b'\x2B\x01\x00')
        self._command(0x44, b'\x00\x31')
        self._command(0x45, b'\x00\x00\x2B\x01')
        self._command(0x18, b'\x80')
        self._command(0x4E, b'\x00')
        self._command(0x4F, b'\x00\x00')
        self.wait_until_idle()

    def _load_partial_lut(self):
        self._command(0x32, LUT_PARTIAL)
        self._command(0x3C, b'\x80')
        self._command(0x21, b'\x00\x00')
        # no wait_until_idle — just register writes, no activation
        self.wait_until_idle()

    def display_frame(self, frame_buffer):
        self._command(0x4E, b'\x00')
        self._command(0x4F, b'\x00\x00')
        self._command(0x24)
        self._data(frame_buffer)
        self._command(0x22, b'\xF7')
        self._command(0x20)
        self.wait_until_idle()
        self._prev_buf = bytearray(frame_buffer)
        self._load_partial_lut()   # ← pre-load LUT once, stays loaded

    def display_frame_partial(self, frame_buffer):
        # Previous frame → RAM 0x26
        self._command(0x4E, b'\x00')
        self._command(0x4F, b'\x00\x00')
        self._command(0x26)
        if self._prev_buf is not None:
            self._data(self._prev_buf)
        else:
            self._data(bytearray(b'\xff' * len(frame_buffer)))

        # New frame → RAM 0x24
        self._command(0x4E, b'\x00')
        self._command(0x4F, b'\x00\x00')
        self._command(0x24)
        self._data(frame_buffer)

        self._command(0x22, b'\xCF')
        self._command(0x20)
        self.wait_until_idle()     # ← must not remove this
        self._prev_buf = bytearray(frame_buffer)

    def clear(self, color=0xFF):
        self._command(0x4E, b'\x00')
        self._command(0x4F, b'\x00\x00')
        self._command(0x24)
        buf = bytearray([color] * (EPD_WIDTH // 8))
        for _ in range(EPD_HEIGHT):
            self._data(buf)
        self._command(0x22, b'\xF7')
        self._command(0x20)
        self.wait_until_idle()

    def sleep(self):
        self._command(0x10, b'\x01')