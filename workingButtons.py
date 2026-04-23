# main.py — Pride & Prejudice e-Paper Reader
# Waveshare 4.2" e-Paper V2 via ESP32 Driver Board
# Buttons on GPIO 32 (next page) and GPIO 33 (prev page)
# Settings button on GPIO 4 (long press = open settings, short press = select)
# LSM6DS3 accelerometer/step counter on I2C GPIO 21 (SDA), 22 (SCL)
 
from machine import Pin, SoftSPI, I2C
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
print("Display ready.")
 
# ── Button init ───────────────────────────────────────────────────────────────
btn_next     = Pin(32, Pin.IN, Pin.PULL_UP)
btn_prev     = Pin(33, Pin.IN, Pin.PULL_UP)
btn_settings = Pin(4, Pin.IN, Pin.PULL_UP)  
 
# ── I2C / LSM6DS3 init ────────────────────────────────────────────────────────
i2c = I2C(0, scl=Pin(22), sda=Pin(21), freq=400000)
 
LSM6DS3_ADDR       = 0x6B   # or 0x6A if SA0 is low
LSM6DS3_WHO_AM_I   = 0x0F
LSM6DS3_CTRL1_XL   = 0x10   # accel control
LSM6DS3_STEP_CTR_L = 0x4B   # step count low byte
LSM6DS3_STEP_CTR_H = 0x4C   # step count high byte
LSM6DS3_TAP_CFG    = 0x58   # enable pedometer
LSM6DS3_CTRL10_C   = 0x19   # enable step counter/pedometer func
 
def lsm6ds3_init():
    try:
        who = i2c.readfrom_mem(LSM6DS3_ADDR, LSM6DS3_WHO_AM_I, 1)
        print("LSM6DS3 WHO_AM_I: 0x{:02X}".format(who[0]))  # expect 0x69
        # Set accel to 26 Hz, ±2g
        i2c.writeto_mem(LSM6DS3_ADDR, LSM6DS3_CTRL1_XL, bytes([0x20]))
        # Enable pedometer in TAP_CFG (bit 6 = TIMER_EN, bit 4 = PEDO_EN)
        i2c.writeto_mem(LSM6DS3_ADDR, LSM6DS3_TAP_CFG,  bytes([0x40]))
        # Enable step counter (bit 3 = PEDO_RST_STEP=0, bit 2 = FUNC_EN=1)
        i2c.writeto_mem(LSM6DS3_ADDR, LSM6DS3_CTRL10_C, bytes([0x04]))
        print("LSM6DS3 pedometer enabled.")
        return True
    except Exception as e:
        print("LSM6DS3 init failed:", e)
        return False
 
def lsm6ds3_steps():
    try:
        lo = i2c.readfrom_mem(LSM6DS3_ADDR, LSM6DS3_STEP_CTR_L, 1)[0]
        hi = i2c.readfrom_mem(LSM6DS3_ADDR, LSM6DS3_STEP_CTR_H, 1)[0]
        return (hi << 8) | lo
    except Exception as e:
        print("LSM6DS3 read failed:", e)
        return -1
 
# ── Profiling ─────────────────────────────────────────────────────────────────
def profile_memory(label):
    gc.collect()
    free  = gc.mem_free()
    alloc = gc.mem_alloc()
    total = free + alloc
    print("[MEM] {:30s} free={:6d}  used={:6d}  total={:6d}".format(
        label, free, alloc, total))
    return free, alloc
 
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
BUF_SIZE = SCREEN_W * SCREEN_H // 8   # 15000 bytes for 400x300
 
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
    profile_memory("before build_frame")
    t0  = time.ticks_ms()
    buf = build_frame(page_lines, page_num, total_pages)
    build_ms = time.ticks_diff(time.ticks_ms(), t0)
    profile_memory("after  build_frame")
    print("[TIME] build_frame {}ms".format(build_ms))
    t0 = time.ticks_ms()
    if full:
        epd.display_frame(buf)
    else:
        epd.display_frame_partial(buf)
    print("[TIME] display write+wait {}ms".format(time.ticks_diff(time.ticks_ms(), t0)))
    del buf
    gc.collect()
    profile_memory("after  display (buf freed)")
 
# ── Settings page renderer ────────────────────────────────────────────────────
SETTINGS_OPTIONS = ["READ", "WALK"]
 
def render_settings(selected_idx):
    """Draw the settings menu with a cursor next to the selected option."""
    epd.init()
    buf = bytearray(BUF_SIZE)
    fb  = framebuf.FrameBuffer(buf, SCREEN_W, SCREEN_H, framebuf.MONO_HLSB)
    fb.fill(0xFF)
 
    title = "-- SETTINGS --"
    fb.text(title, PADDING, PADDING, 0x00)
 
    # Divider line
    fb.hline(PADDING, PADDING + CHAR_H + 4, SCREEN_W - PADDING * 2, 0x00)
 
    for i, option in enumerate(SETTINGS_OPTIONS):
        y = PADDING + CHAR_H * 3 + i * (CHAR_H + 6)
        cursor = "> " if i == selected_idx else "  "
        fb.text(cursor + option, PADDING, y, 0x00)
 
    hint = "UP/DN: navigate  SET: select"
    fb.text(hint,
            PADDING,
            SCREEN_H - CHAR_H - 4,
            0x00)
 
    epd.display_frame(buf)
    del buf
    gc.collect()
 
# ── Walk page renderer ────────────────────────────────────────────────────────
def render_walk_page(steps):
    """Display the current step count on a full-screen walking page."""
    buf = bytearray(BUF_SIZE)
    fb  = framebuf.FrameBuffer(buf, SCREEN_W, SCREEN_H, framebuf.MONO_HLSB)
    fb.fill(0xFF)
 
    title = "WALK MODE"
    fb.text(title, PADDING, PADDING, 0x00)
    fb.hline(PADDING, PADDING + CHAR_H + 4, SCREEN_W - PADDING * 2, 0x00)
 
    if steps < 0:
        step_str = "Sensor error"
        print("curr steps", steps)
    else:
        step_str = "Steps: {}".format(steps)
 
    # Draw step count large-ish by repeating text scaled manually
    # (MicroPython framebuf has no font scaling, so we tile 2x manually)
    label_x = PADDING
    label_y = SCREEN_H // 2 - CHAR_H
    for dy in range(2):
        for dx in range(2):
            fb.text(step_str, label_x + dx, label_y + dy, 0x00)
 
    hint = "NEXT/PREV: refresh  LONG SET: menu"
    fb.text(hint, PADDING, SCREEN_H - CHAR_H - 4, 0x00)
 
    epd.display_frame_partial(buf)
    del buf
    gc.collect()
 
# ── Button helpers ────────────────────────────────────────────────────────────
DEBOUNCE_MS      = 200
LONG_PRESS_MS    = 700   # hold for 700 ms to trigger long-press
 
last_press_next  = 0
last_press_prev  = 0
last_press_set   = 0
 
def button_pressed(pin, last_ref):
    """Returns (True, now) on a debounced falling edge, else (False, last_ref)."""
    if pin.value() == 0:
        now = time.ticks_ms()
        if time.ticks_diff(now, last_ref) > DEBOUNCE_MS:
            return True, now
    return False, last_ref
 
def detect_settings_press():
    """
    Block until GPIO 4 is released, then classify the press.
    Returns 'long' or 'short'.
    Called only after we already detect the button is LOW.
    """
    t_down = time.ticks_ms()
    while btn_settings.value() == 0:
        time.sleep_ms(10)
    held = time.ticks_diff(time.ticks_ms(), t_down)
    return "long" if held >= LONG_PRESS_MS else "short"
 
# ── App modes ─────────────────────────────────────────────────────────────────
MODE_READ     = "read"
MODE_WALK     = "walk"
MODE_SETTINGS = "settings"
 
# ── Startup ───────────────────────────────────────────────────────────────────
profile_memory("startup")
 
accel_ok = lsm6ds3_init()
 
print("Building pages...")
t0    = time.ticks_ms()
pages = build_pages("/sample.txt")
print("[TIME] build_pages {}ms".format(time.ticks_diff(time.ticks_ms(), t0)))
profile_memory("after build_pages")
 
total   = len(pages)
current = 0
 
print("\nRendering first page...")
render_page(pages[current], current, total, full=True)
print("\nReady. Long-press SETTINGS to open menu.")
 
# ── State ─────────────────────────────────────────────────────────────────────
mode         = MODE_READ
settings_idx = 0   # which settings option is highlighted
 
# ── Main loop ─────────────────────────────────────────────────────────────────
while True:
 
    # ── Settings button ───────────────────────────────────────────────────────
    if btn_settings.value() == 0:
        now = time.ticks_ms()
        if time.ticks_diff(now, last_press_set) > DEBOUNCE_MS:
            last_press_set = now
            press_type = detect_settings_press()
 
            if press_type == "long":
                # Enter settings menu from any mode
                mode = MODE_SETTINGS
                settings_idx = 0 if mode != MODE_WALK else 1
                print("Opening settings menu")
                render_settings(settings_idx)
 
            elif press_type == "short" and mode == MODE_SETTINGS:
                # Confirm selection
                chosen = SETTINGS_OPTIONS[settings_idx]
                print("Selected:", chosen)
                if chosen == "READ":
                    epd.init()
                    mode    = MODE_READ
                    current = 0
                    render_page(pages[current], current, total, full=True)
                elif chosen == "WALK":
                    mode  = MODE_WALK
                    steps = lsm6ds3_steps()
                    render_walk_page(steps)
 
    # ── NEXT button ───────────────────────────────────────────────────────────
    pressed, last_press_next = button_pressed(btn_next, last_press_next)
    if pressed:
        if mode == MODE_READ:
            if current < total - 1:
                current += 1
                print("→ Page", current + 1)
                render_page(pages[current], current, total, full=False)
 
        elif mode == MODE_WALK:
            steps = lsm6ds3_steps()
            print("Refreshing steps:", steps)
            i2c = I2C(0, scl=Pin(22), sda=Pin(21), freq=400000)
            print("i2c scan", i2c.scan())
            render_walk_page(steps)
 
        elif mode == MODE_SETTINGS:
            settings_idx = (settings_idx + 1) % len(SETTINGS_OPTIONS)
            render_settings(settings_idx)
 
    # ── PREV button ───────────────────────────────────────────────────────────
    pressed, last_press_prev = button_pressed(btn_prev, last_press_prev)
    if pressed:
        if mode == MODE_READ:
            if current > 0:
                current -= 1
                print("← Page", current + 1)
                render_page(pages[current], current, total, full=False)
 
        elif mode == MODE_WALK:
            steps = lsm6ds3_steps()
            print("Refreshing steps:", steps)
            render_walk_page(steps)
 
        elif mode == MODE_SETTINGS:
            settings_idx = (settings_idx - 1) % len(SETTINGS_OPTIONS)
            render_settings(settings_idx)
 
    time.sleep_ms(50)