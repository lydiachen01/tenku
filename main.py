# main.py — Pride & Prejudice e-Paper Reader
# Waveshare 4.2" e-Paper V2 via ESP32 Driver Board
# Buttons on GPIO 32 (next page) and GPIO 33 (prev page)

from machine import Pin, SoftSPI
import framebuf
import time
import gc
from epaper4in2_2 import EPD

# ── Display config ────────────────────────────────────────────────────────────
SCREEN_W     = 400
SCREEN_H     = 300
PADDING      = 8
CHAR_W       = 10
CHAR_H       = 10

TEXT_W = SCREEN_W - (PADDING * 2)
TEXT_H = SCREEN_H - (PADDING * 2)

COLS = TEXT_W // CHAR_W   # 38
ROWS = TEXT_H // CHAR_H   # 29

# ── SPI / display init ────────────────────────────────────────────────────────
spi  = SoftSPI(baudrate=2000000, polarity=0, phase=0,
               sck=Pin(13), mosi=Pin(14), miso=Pin(12))
cs   = Pin(15)
dc   = Pin(27)
rst  = Pin(26)
busy = Pin(25)

print("Initialising display...")
epd = EPD(spi, cs, dc, rst, busy)
epd.init()
epd.clear()
epd.init()
print("Display ready.")

# ── Button init ───────────────────────────────────────────────────────────────
btn_next = Pin(32, Pin.IN, Pin.PULL_UP)
btn_prev = Pin(33, Pin.IN, Pin.PULL_UP)

# ── Profiling ─────────────────────────────────────────────────────────────────
def profile_memory(label):
    gc.collect()
    free  = gc.mem_free()
    alloc = gc.mem_alloc()
    total = free + alloc
    print("[MEM] {:30s} free={:6d}  used={:6d}  total={:6d}".format(
        label, free, alloc, total))
    return free, alloc

def profile_time(label, fn):
    """Call fn(), print how long it took, return its result."""
    t0 = time.ticks_ms()
    result = fn()
    elapsed = time.ticks_diff(time.ticks_ms(), t0)
    print("[TIME] {:30s} {}ms".format(label, elapsed))
    return result

# ── Text pagination ───────────────────────────────────────────────────────────
def build_pages(filepath):
    print("Reading file:", filepath)
    with open(filepath, "r") as f:
        raw = f.read()

    raw = raw.replace("\r\n", " ").replace("\n", " ").replace("\t", " ")
    words = [w for w in raw.split(" ") if w]

    pages = []
    current_lines = []
    current_line  = ""

    for word in words:
        if len(word) > COLS:
            word = word[:COLS]
        tentative = word if current_line == "" else current_line + " " + word
        if len(tentative) <= COLS:
            current_line = tentative
        else:
            current_lines.append(current_line)
            current_line = word
            if len(current_lines) >= ROWS:
                pages.append(current_lines[:ROWS])
                current_lines = []

    if current_line:
        current_lines.append(current_line)
    if current_lines:
        pages.append(current_lines)

    print("Total pages:", len(pages))
    return pages

# ── Rendering ─────────────────────────────────────────────────────────────────
BUF_SIZE = SCREEN_W * SCREEN_H // 8   # bytes — always 15000 for 400x300

def build_frame(page_lines, page_num, total_pages):
    buf = bytearray(BUF_SIZE)
    fb  = framebuf.FrameBuffer(buf, SCREEN_W, SCREEN_H, framebuf.MONO_HLSB)
    fb.fill(0xFF)
    for row_idx, line in enumerate(page_lines):
        fb.text(line, PADDING, PADDING + (row_idx * CHAR_H), 0x00)
    indicator = "{}/{}".format(page_num + 1, total_pages)
    fb.text(indicator,
            SCREEN_W - PADDING - (len(indicator) * CHAR_W),
            SCREEN_H - CHAR_H - 2,
            0x00)
    return buf


def render_page(page_lines, page_num, total_pages, full=False):
    mode = "full" if full else "partial"
    print("\n--- render_page {}/{} ({}) ---".format(page_num + 1, total_pages, mode))

    # Memory before frame build
    profile_memory("before build_frame")

    # Time the frame build
    t0 = time.ticks_ms()
    buf = build_frame(page_lines, page_num, total_pages)
    build_ms = time.ticks_diff(time.ticks_ms(), t0)

    # Memory after frame build (buf is now allocated)
    profile_memory("after  build_frame")
    print("[SIZE] frame buffer               {} bytes ({} KB)".format(
        len(buf), len(buf) // 1024))
    print("[TIME] build_frame                {}ms".format(build_ms))

    # Time the display write
    t0 = time.ticks_ms()
    if full:
        #epd.init()
        epd.display_frame(buf)
    else:
        epd.display_frame_partial(buf)
    display_ms = time.ticks_diff(time.ticks_ms(), t0)

    print("[TIME] display write+wait         {}ms".format(display_ms))
    print("[TIME] total                      {}ms".format(build_ms + display_ms))

    # Memory after display (buf can now be GC'd if nothing holds a reference)
    del buf
    gc.collect()
    profile_memory("after  display (buf freed)")

# ── Button debounce ───────────────────────────────────────────────────────────
DEBOUNCE_MS     = 200
last_press_next = 0
last_press_prev = 0

def button_pressed(pin, last_ref):
    if pin.value() == 0:
        now = time.ticks_ms()
        if time.ticks_diff(now, last_ref) > DEBOUNCE_MS:
            return True, now
    return False, last_ref

# ── Main ──────────────────────────────────────────────────────────────────────
profile_memory("startup")

print("Building pages...")
t0 = time.ticks_ms()
pages = build_pages("/sample.txt")
print("[TIME] build_pages                {}ms".format(time.ticks_diff(time.ticks_ms(), t0)))
profile_memory("after build_pages")

total   = len(pages)
current = 0

# Also report _prev_buf size in the driver (stored after first display_frame)
print("[SIZE] _prev_buf in driver        {} bytes (allocated after first render)".format(
    SCREEN_W * SCREEN_H // 8))

print("\nRendering first page...")
render_page(pages[current], current, total, full=True)
print("\nReady. Use buttons to turn pages.")

while True:
    pressed, last_press_next = button_pressed(btn_next, last_press_next)
    if pressed:
        if current < total - 1:
            current += 1
            print("→ Page", current + 1)
            render_page(pages[current], current, total, full=False)

    pressed, last_press_prev = button_pressed(btn_prev, last_press_prev)
    if pressed:
        if current > 0:
            current -= 1
            print("← Page", current + 1)
            render_page(pages[current], current, total, full=False)

    time.sleep_ms(50)