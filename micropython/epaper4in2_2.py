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
            sleep_ms(2)

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
        # CHANGE HERE self.wait_until_idle()

    def display_frame(self, frame_buffer):
        self._command(0x3C, b'\x05')
        self._command(0x21, b'\x40\x00')

        # RAM 0x24 — new frame
        self._command(0x4E, b'\x00')
        self._command(0x4F, b'\x00\x00')
        self._command(0x24)
        self._data(frame_buffer)

        # RAM 0x26 — same frame (so hardware "previous" matches what's on screen)
        self._command(0x4E, b'\x00')
        self._command(0x4F, b'\x00\x00')
        self._command(0x26)
        self._data(frame_buffer)  # ← walk layout, not white

        self._command(0x22, b'\xF7')
        self._command(0x20)
        self.wait_until_idle()
#         self._prev_buf = bytearray(frame_buffer)
        if self._prev_buf is None:
            self._prev_buf = bytearray(len(frame_buffer))

        self._prev_buf[:] = frame_buffer
        self._load_partial_lut()
        sleep_ms(100)

    def display_frame_partial(self, frame_buffer):
        # Previous frame → RAM 0x26
        self._command(0x4E, b'\x00')
        self._command(0x4F, b'\x00\x00')
        self._command(0x26) #The next data you receive should go into the previous image buffer (RAM 0x26)
        if self._prev_buf is not None:
            self._data(self._prev_buf)
        else:
            # Avoid allocating a full 15000-byte temporary buffer.
            white_row = bytearray([0xFF] * (EPD_WIDTH // 8))
            for _ in range(EPD_HEIGHT):
                self._data(white_row)

        # New frame → RAM 0x24
        self._command(0x4E, b'\x00')
        self._command(0x4F, b'\x00\x00')
        self._command(0x24) #write this upcoming data
        self._data(frame_buffer)

        self._command(0x22, b'\xCF') #update the display
        self._command(0x20)
        self.wait_until_idle()     # ← must not remove this
        if self._prev_buf is not None:
            self._prev_buf[:] = frame_buffer
        
    def display_frame_no_prev(self, frame_buffer):
        """
        Full refresh without allocating/updating _prev_buf.
        Use this before deep sleep or reset, when partial-refresh history
        does not matter.
        """
        self._command(0x3C, b'\x05')
        self._command(0x21, b'\x40\x00')

        # RAM 0x24 — new frame
        self._command(0x4E, b'\x00')
        self._command(0x4F, b'\x00\x00')
        self._command(0x24)
        self._data(frame_buffer)

        # RAM 0x26 — same frame
        self._command(0x4E, b'\x00')
        self._command(0x4F, b'\x00\x00')
        self._command(0x26)
        self._data(frame_buffer)

        self._command(0x22, b'\xF7')
        self._command(0x20)
        self.wait_until_idle()
        sleep_ms(100)

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
    
    def display_frame_partial_window(self, frame_buffer, x, y, w, h):
        """
        Partial refresh of a rectangular region only.
        x, w must be byte-aligned (multiples of 8).
        frame_buffer must be exactly (w // 8) * h bytes —
        only the pixels for the bounding box, not the full screen.
        """
        x_start = x // 8
        x_end   = (x + w) // 8 - 1
        y_start = y
        y_end   = y + h - 1

        # Set X window
        self._command(0x44, bytearray([x_start, x_end]))
        # Set Y window
        self._command(0x45, bytearray([
            y_start & 0xFF, (y_start >> 8) & 0xFF,
            y_end   & 0xFF, (y_end   >> 8) & 0xFF,
        ]))
        # Set cursor to top-left of window
        self._command(0x4E, bytearray([x_start]))
        self._command(0x4F, bytearray([y_start & 0xFF, (y_start >> 8) & 0xFF]))

        # Write previous frame data for the window region into RAM 0x26
        self._command(0x26)
        if self._prev_buf is not None:
            self._data(self._extract_window(self._prev_buf, x, y, w, h))
        else:
            self._data(bytearray(b'\xff' * ((w // 8) * h)))

        # Reset cursor, write new frame data into RAM 0x24
        self._command(0x4E, bytearray([x_start]))
        self._command(0x4F, bytearray([y_start & 0xFF, (y_start >> 8) & 0xFF]))
        self._command(0x24)
        self._data(frame_buffer)

        self._command(0x22, b'\xCF')
        self._command(0x20)
        self.wait_until_idle()

        # Patch _prev_buf so subsequent partial updates stay consistent
        if self._prev_buf is not None:
            self._patch_window(self._prev_buf, frame_buffer, x, y, w, h)

        # Restore full-screen window for next full/normal partial update
        self._command(0x44, b'\x00\x31')
        self._command(0x45, b'\x00\x00\x2B\x01')
        self._command(0x4E, b'\x00')
        self._command(0x4F, b'\x00\x00')

    def _extract_window(self, full_buf, x, y, w, h):
        """Pull a w x h rectangle out of a full 400x300 frame buffer."""
        stride    = EPD_WIDTH // 8   # 50 bytes per row
        win_stride = w // 8
        out = bytearray(win_stride * h)
        x_byte = x // 8
        for row in range(h):
            src = (y + row) * stride + x_byte
            dst = row * win_stride
            out[dst:dst + win_stride] = full_buf[src:src + win_stride]
        return out

    def _patch_window(self, full_buf, win_buf, x, y, w, h):
        print("_patch_window full_buf id:", id(full_buf))
        print("self._prev_buf id:", id(self._prev_buf))
        if full_buf is None:
            print("_patch_window: full_buf is None, aborting")
            return
        stride     = EPD_WIDTH // 8  # 50
        win_stride = w // 8
        x_byte     = x // 8
        print("_patch_window: x={} y={} w={} h={} x_byte={} win_stride={}".format(x,y,w,h,x_byte,win_stride))
        for row in range(h):
            dst = (y + row) * stride + x_byte
            src = row * win_stride
            if any(b != 0xFF for b in win_buf[src:src+win_stride]):
                print("  ink row {}: src={} dst={} data={}".format(row, src, dst, list(win_buf[src:src+win_stride])))
            full_buf[dst:dst + win_stride] = win_buf[src:src + win_stride]
        print("_patch_window done, checking dst 6655:", list(full_buf[6655:6660]))
            
    def clear_prev_buf(self):
        """Reset stored previous frame AND hardware RAM 0x26 to all-white."""
        if self._prev_buf is not None:
            for i in range(len(self._prev_buf)):
                self._prev_buf[i] = 0xFF
        else:
            self._prev_buf = bytearray(b'\xff' * (self.width * self.height // 8))

        # Flush white into controller RAM 0x26 so hardware state matches _prev_buf
        self._command(0x4E, b'\x00')
        self._command(0x4F, b'\x00\x00')
        self._command(0x26)
        white = bytearray(b'\xff' * (EPD_WIDTH // 8))
        for _ in range(EPD_HEIGHT):
            self._data(white)

