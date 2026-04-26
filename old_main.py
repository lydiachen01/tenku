# main.py — Pride & Prejudice e-Paper Reader
# Waveshare 4.2" e-Paper V2 via ESP32 Driver Board
# Buttons on GPIO 32 (next page) and GPIO 33 (prev page)
# Settings button on GPIO 4 (long press = open settings, short press = select)
# LSM6DS3 accelerometer/step counter on I2C GPIO 21 (SDA), 22 (SCL)

import esp32
import machine
from machine import Pin, SoftSPI, I2C
import framebuf
import time
import gc
from epaper4in2_2 import EPD
import sprites  # walk_0.png / walk_1.png converted via convert_sprites.py
from time import sleep_ms

START_IN_LOW_POWER_MODE = True

class Button:
    def __init__(self, pin, debounce_ms=200, long_press_ms=700):
        self.pin = pin
        self.debounce_ms = debounce_ms
        self.long_press_ms = long_press_ms
        self.last_press = 0

    def read(self):
        if self.pin.value() != 0:
            return None

        now = time.ticks_ms()

        if time.ticks_diff(now, self.last_press) <= self.debounce_ms:
            return None

        self.last_press = now
        t_down = now

        # detect long press in background
        while self.pin.value() == 0:
            held = time.ticks_diff(time.ticks_ms(), t_down)

            if held >= self.long_press_ms:
                while self.pin.value() == 0:
                    time.sleep_ms(20)
                return "long"

            time.sleep_ms(10)

        return "short"
 
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
 
# ── Sprite / walk page layout ─────────────────────────────────────────────────
SPR_W = sprites.SPRITE_W   # 40
SPR_H = sprites.SPRITE_H   # 40
 
# Sprite centered vertically, left quarter of screen
# x must be a multiple of 8
SPR_X = 40                              # 40px from left edge
SPR_Y = (SCREEN_H - SPR_H) // 2        # vertically centred = 130
 
# Step counter text — centered in right half of screen
STEP_TEXT_X = SCREEN_W // 2 + 16       # ~216px from left (multiple of 8)
STEP_TEXT_Y = (SCREEN_H - CHAR_H) // 2 # vertically centred
 
# Animation state
_walk_frame = 0
 
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
btn_next_pin     = Pin(32, Pin.IN, Pin.PULL_UP)
btn_prev_pin     = Pin(33, Pin.IN, Pin.PULL_UP)
btn_settings_pin = Pin(4,  Pin.IN, Pin.PULL_UP)

next_btn = Button(btn_next_pin, debounce_ms=200, long_press_ms=700)
prev_btn = Button(btn_prev_pin, debounce_ms=200, long_press_ms=700)
settings_btn = Button(btn_settings_pin, debounce_ms=200, long_press_ms=700)
 
# ── I2C / LSM6DS3 init ────────────────────────────────────────────────────────
i2c = I2C(0, scl=Pin(22), sda=Pin(21), freq=400000)
 
LSM6DS3_ADDR       = 0x6B
LSM6DS3_WHO_AM_I   = 0x0F
LSM6DS3_CTRL1_XL   = 0x10
LSM6DS3_STEP_CTR_L = 0x4B
LSM6DS3_STEP_CTR_H = 0x4C
LSM6DS3_TAP_CFG    = 0x58
LSM6DS3_CTRL10_C   = 0x19
 
def lsm6ds3_init():
    try:
        who = i2c.readfrom_mem(LSM6DS3_ADDR, LSM6DS3_WHO_AM_I, 1)
        print("LSM6DS3 WHO_AM_I: 0x{:02X}".format(who[0]))
        i2c.writeto_mem(LSM6DS3_ADDR, LSM6DS3_CTRL1_XL, bytes([0x20]))
        i2c.writeto_mem(LSM6DS3_ADDR, LSM6DS3_TAP_CFG,  bytes([0x40]))
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
SETTINGS_OPTIONS = ["READ", "WALK", "DEVICE"]
 
def render_settings(selected_idx):
    """Draw the settings menu with a cursor next to the selected option."""
    
    buf = bytearray(BUF_SIZE)
    fb  = framebuf.FrameBuffer(buf, SCREEN_W, SCREEN_H, framebuf.MONO_HLSB)
    fb.fill(0xFF)
 
    title = "-- SETTINGS --"
    fb.text(title, PADDING, PADDING, 0x00)
    fb.hline(PADDING, PADDING + CHAR_H + 4, SCREEN_W - PADDING * 2, 0x00)
 
    for i, option in enumerate(SETTINGS_OPTIONS):
        y = PADDING + CHAR_H * 3 + i * (CHAR_H + 6)
        cursor = "> " if i == selected_idx else "  "
        fb.text(cursor + option, PADDING, y, 0x00)
 
    hint = "UP/DN: navigate  SET: select"
    fb.text(hint, PADDING, SCREEN_H - CHAR_H - 4, 0x00)
 
    epd.display_frame(buf)
    del buf
    gc.collect()
 
# ── Walk page ─────────────────────────────────────────────────────────────────
def render_walk_page_full(steps):
    buf = bytearray(BUF_SIZE)
    fb  = framebuf.FrameBuffer(buf, SCREEN_W, SCREEN_H, framebuf.MONO_HLSB)
    fb.fill(0xFF)

    fb.text("WALK MODE", PADDING, PADDING, 0x00)
    fb.hline(PADDING, PADDING + CHAR_H + 4, SCREEN_W - PADDING * 2, 0x00)
    fb.vline(SCREEN_W // 2, PADDING + CHAR_H + 8,
             SCREEN_H - PADDING * 2 - CHAR_H - 28, 0x00)
    fb.text("NEXT/PREV: refresh  LONG SET: menu",
            PADDING, SCREEN_H - CHAR_H - 4, 0x00)

    epd.display_frame(buf)
    # Do NOT call clear_prev_buf() here.
    # _prev_buf = walk layout, RAM 0x26 = walk layout (set by display_frame).
    # Windowed partials will correctly diff sprite/steps against this background.
    del buf
    gc.collect()
    _render_sprite_window(0)
    print("SPRITE LENGTH", len(sprites.FRAMES[0]))
    sleep_ms(1000)
    render_walk_update(steps)
#     _render_step_window(steps)
 
 
def _render_sprite_window(frame_idx):
    win_buf = bytearray(sprites.FRAMES[frame_idx])
    
    # Find which row in win_buf actually has ink
    for row in range(SPR_H):
        row_bytes = list(win_buf[row*5:(row*5)+5])
        if any(b != 0xFF for b in row_bytes):
            print("Sprite ink at win_buf row {}: {}".format(row, row_bytes))
            # Where should this end up in _prev_buf?
            expected_idx = (SPR_Y + row) * 50 + (SPR_X // 8)
            print("Should patch _prev_buf at byte index:", expected_idx)
            break
    
    epd.display_frame_partial_window(win_buf, SPR_X, SPR_Y, SPR_W, SPR_H)
    
    # Check that exact location after patch
    expected_idx = (SPR_Y + 2) * 50 + (SPR_X // 8)  # row 2 of sprite = screen row 132
    print("_prev_buf at expected patch location:", list(epd._prev_buf[expected_idx:expected_idx+5]))
    del win_buf
    gc.collect()
    print("After GC, _prev_buf id:", id(epd._prev_buf))
    print("After GC, _prev_buf[6655]:", list(epd._prev_buf[6655:6660]))
 
 
def _render_step_window(steps):
    # NO epd.init() here — it issues SW_RESET which wipes the partial LUT
    # loaded by display_frame() and destroys _prev_buf coherence, causing
    # the darkening and blank steps you observed.
    WIN_W = 136
    WIN_H = CHAR_H * 2 + 4
    WIN_X = STEP_TEXT_X
    WIN_Y = STEP_TEXT_Y - 2

    win_buf = bytearray((WIN_W // 8) * WIN_H)
    fb = framebuf.FrameBuffer(win_buf, WIN_W, WIN_H, framebuf.MONO_HLSB)
    fb.fill(0xFF)

    if steps < 0:
        line1 = "Sensor"
        line2 = "error"
        print("curr steps", steps)
    else:
        line1 = "Steps:"
        line2 = str(steps)

    fb.text(line1, 0, 0,          0x00)
    fb.text(line2, 0, CHAR_H + 2, 0x00)
    print(line1, line2, "steps should have been on screen")

    epd.display_frame_partial_window(win_buf, WIN_X, WIN_Y, WIN_W, WIN_H)
    del win_buf
    gc.collect()
 
 
def render_walk_update(steps):
    """
    Called on each button press in walk mode.
    Advances animation frame and refreshes only the two bounding boxes.
    """
    global _walk_frame
    print("IN UPDATE WALK FRAME")
    _walk_frame = (_walk_frame + 1) % len(sprites.FRAMES)
    _render_sprite_window(_walk_frame)
    _render_step_window(steps)
    
def center_text(text):
    x = (SCREEN_W - len(text) * CHAR_W) // 2
    y = (SCREEN_H - CHAR_H) // 2
    return (x, y)

# ── Button helpers ────────────────────────────────────────────────────────────
DEBOUNCE_MS      = 200
LONG_PRESS_MS    = 700
 
last_press_next  = 0
last_press_prev  = 0
last_press_set   = 0
 
# ── ON/OFF ─────────────────────────────────────────────────────────────────
POWER_HOLD_MS = 3000
WAKE_PIN = btn_next_pin

def enter_low_power_mode():
    print("Entering low power mode...")
    buf = bytearray(BUF_SIZE)
    fb = framebuf.FrameBuffer(buf, SCREEN_W, SCREEN_H, framebuf.MONO_HLSB)
    fb.fill(0x00)
    start_txt = "TENKU"
    center_x, center_y = center_text(start_txt)
    fb.text(start_txt, center_x, center_y, 0xFF) 
    epd.display_frame(buf)
    
    del buf
    gc.collect()
    epd.sleep()

    # Put LSM6DS3 accel into low-power/off-ish mode
    try:
        i2c.writeto_mem(LSM6DS3_ADDR, LSM6DS3_CTRL1_XL, bytes([0x00]))
        i2c.writeto_mem(LSM6DS3_ADDR, LSM6DS3_CTRL10_C, bytes([0x00]))
    except Exception as e:
        print("Sensor sleep failed:", e)

    # Wait for button to be released
    while btn_next_pin.value() == 0:
        time.sleep_ms(20)
    
    time.sleep_ms(200)  # Debounce
    
    # Configure wake on button press (LOW)
    print("Configuring wake on GPIO32 (NEXT button)...")
    esp32.wake_on_ext0(pin=WAKE_PIN, level=esp32.WAKEUP_ALL_LOW)

    print("Deep sleeping. Press NEXT button to wake...")
    time.sleep_ms(500)
    
    machine.deepsleep()
 
# def button_pressed(pin, last_ref):
#     if pin.value() == 0:
#         now = time.ticks_ms()
#         if time.ticks_diff(now, last_ref) > DEBOUNCE_MS:
#             return True, now
#     return False, last_ref
#  
# def detect_settings_press():
#     t_down = time.ticks_ms()
#     while btn_settings.value() == 0:
#         time.sleep_ms(5)
#     held = time.ticks_diff(time.ticks_ms(), t_down)
#     return "long" if held >= LONG_PRESS_MS else "short"
#  
# ── App modes ─────────────────────────────────────────────────────────────────
MODE_READ     = "read"
MODE_WALK     = "walk"
MODE_DEVICE = "device"
MODE_SETTINGS = "settings"
 
# ── Startup ───────────────────────────────────────────────────────────────────
profile_memory("startup")

print("=== STARTUP ===")
print("Wake reason:", machine.wake_reason())
print("DEEPSLEEP_RESET value:", machine.DEEPSLEEP_RESET)

accel_ok = lsm6ds3_init()

if machine.wake_reason() == 0:  # 0 = power-on/reset
    if START_IN_LOW_POWER_MODE:
        print("Fresh boot. Entering low power mode...")
        enter_low_power_mode()
    else:
        epd.init()
else:
    # Woke from sleep (any external event)
    print("Woke from deep sleep. Reinitializing...")
    epd.init()

print("Building pages...")
t0    = time.ticks_ms()
pages = build_pages("/sample.txt")
print("[TIME] build_pages {}ms".format(time.ticks_diff(time.ticks_ms(), t0)))
profile_memory("after build_pages")
 
total   = len(pages)
current = 0
 
# render_page(pages[current], current, total, full=True)
 
# ── State ─────────────────────────────────────────────────────────────────────
mode         = MODE_SETTINGS
settings_idx = 0
 
print("\nStarting in settings menu...")
render_settings(settings_idx)
print("\nReady. Select READ or WALK.")
 
# ── Main loop ─────────────────────────────────────────────────────────────────
while True:
 
#     # ── Settings button ───────────────────────────────────────────────────────
#     if btn_settings.value() == 0:
#         now = time.ticks_ms()
#         if time.ticks_diff(now, last_press_set) > DEBOUNCE_MS:
#             last_press_set = now
#             press_type = detect_settings_press()
#  
#             if press_type == "long":
#                 mode = MODE_SETTINGS
#                 settings_idx = 0
#                 print("Opening settings menu")
#                 render_settings(settings_idx)
#  
#             elif press_type == "short" and mode == MODE_SETTINGS:
#                 chosen = SETTINGS_OPTIONS[settings_idx]
#                 print("Selected:", chosen)
#                 if chosen == "READ":
#                     epd.init()
#                     mode    = MODE_READ
#                     current = 0
#                     render_page(pages[current], current, total, full=True)
#                 elif chosen == "WALK":
#                     mode        = MODE_WALK
#                     _walk_frame = 0
#                     steps       = lsm6ds3_steps()
#                     render_walk_page_full(steps)
 
# ── NEXT button ───────────────────────────────────────────────────────────
#     pressed, last_press_next = button_pressed(btn_next, last_press_next)
#     if pressed:
#         if mode == MODE_READ:
#             if current < total - 1:
#                 current += 1
#                 print("→ Page", current + 1)
#                 render_page(pages[current], current, total, full=False)
#  
#         elif mode == MODE_WALK:
#             steps = lsm6ds3_steps()
#             print("Refreshing steps:", steps)
#             render_walk_update(steps)
#  
#         elif mode == MODE_SETTINGS:
#             settings_idx = (settings_idx + 1) % len(SETTINGS_OPTIONS)
#             render_settings(settings_idx)
# ── PREV button ───────────────────────────────────────────────────────────
#     pressed, last_press_prev = button_pressed(btn_prev, last_press_prev)
#     if pressed:
#         if mode == MODE_READ:
#             if current > 0:
#                 current -= 1
#                 print("← Page", current + 1)
#                 render_page(pages[current], current, total, full=False)
#  
#         elif mode == MODE_WALK:
#             steps = lsm6ds3_steps()
#             print("Refreshing steps:", steps)
#             render_walk_update(steps)
#  
#         elif mode == MODE_SETTINGS:
#             settings_idx = (settings_idx - 1) % len(SETTINGS_OPTIONS)
#             render_settings(settings_idx)

    next_action = next_btn.read()
    prev_action = prev_btn.read()
    settings_action = settings_btn.read()

    # ── SETTINGS button ───────────────────────────────────────────────────────
    if settings_action == "long":
        mode = MODE_SETTINGS
        settings_idx = 0
        render_settings(settings_idx)

    elif settings_action == "short" and mode == MODE_SETTINGS:
        chosen = SETTINGS_OPTIONS[settings_idx]

        if chosen == "READ":
            epd.init()
            mode = MODE_READ
            current = 0
            render_page(pages[current], current, total, full=True)

        elif chosen == "WALK":
            mode = MODE_WALK
            _walk_frame = 0
            steps = lsm6ds3_steps()
            render_walk_page_full(steps)
        
        elif chose == "DEVICE":
            mode = MODE_DEVICE
            # make a device config page for configuring font size from nvm
            device_config_idx = 0
                render_device_config(device_config_idx)


    # ── NEXT button ───────────────────────────────────────────────────────────
    
    if next_action == "long":
        enter_low_power_mode()

    elif next_action == "short":
        if mode == MODE_READ:
            if current < total - 1:
                current += 1
                render_page(pages[current], current, total, full=False)

        elif mode == MODE_WALK:
            steps = lsm6ds3_steps()
            render_walk_update(steps)

        elif mode == MODE_SETTINGS:
            settings_idx = (settings_idx + 1) % len(SETTINGS_OPTIONS)
            render_settings(settings_idx)
 
    # ── PREV button ───────────────────────────────────────────────────────────
    if prev_action == "short":
        if mode == MODE_READ:
            if current > 0:
                current -= 1
                render_page(pages[current], current, total, full=False)

        elif mode == MODE_WALK:
            steps = lsm6ds3_steps()
            render_walk_update(steps)

        elif mode == MODE_SETTINGS:
            settings_idx = (settings_idx - 1) % len(SETTINGS_OPTIONS)
            render_settings(settings_idx)
 
    time.sleep_ms(10)

