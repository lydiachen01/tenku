# main.py — Tenku e-Paper Reader
# Waveshare 4.2" e-Paper V2 via ESP32 Driver Board
# ESP32-WROOM + LSM6DS3 + buttons + book list + per-book byte-offset memory

import os
import esp32
import machine
from machine import Pin, SoftSPI, I2C
import framebuf
import time
import gc
from time import sleep_ms

from epaper4in2_2 import EPD

UPLOAD_BOOT_FLAG = b"UPLOAD"
WIFI_SSID = "Tufts_Wireless"
WIFI_PASSWORD = None
UPLOAD_MAX_FILE_SIZE = 100000

# ── Profiling ─────────────────────────────────────────────────────────────────
def profile_memory(label):
    gc.collect()
    free = gc.mem_free()
    alloc = gc.mem_alloc()
    total = free + alloc
    print("[MEM] {:30s} free={:6d} used={:6d} total={:6d}".format(label, free, alloc, total))
    return free, alloc

def connect_to_wifi():
    """
    Connect to WiFi and return the first IP address from the station interface.
    Returns None if connection fails.
    """
    import network
    
    try:
        sta = network.WLAN(network.STA_IF)
        
        if not sta.active():
            sta.active(True)
            
        if not sta.isconnected():
            print("Connecting to WiFi: {}".format(WIFI_SSID))
            sta.connect(WIFI_SSID, WIFI_PASSWORD)
            
            timeout = 100
            while not sta.isconnected() and timeout > 0:
                sleep_ms(100)
                timeout -= 1
        
        if sta.isconnected():
            ifconfig = sta.ifconfig()
            ip = ifconfig[0]
            print("WiFi connected. IP: {}".format(ip))
            return ip
        else:
            print("Failed to connect to WiFi")
            return None
            
    except Exception as e:
        print("WiFi connection error:", e)
        return None

# ── Clean upload boot path ────────────────────────────────────────────────────
def run_upload_boot_mode():
    print("Booting into upload mode...")

    gc.collect()
    profile_memory("upload boot start")

    # Connect WiFi FIRST.
    # Do not import upload_server yet.
    ip = connect_to_wifi()

    gc.collect()
    profile_memory("after wifi connect")

    # Only now import upload_server.
    import upload_server

    # Only now set up the display.
    screen_w = 400
    screen_h = 300
    padding = 8
    char_h = 10
    buf_size = screen_w * screen_h // 8

    screen_buf = bytearray(buf_size)
    screen_fb = framebuf.FrameBuffer(
        screen_buf,
        screen_w,
        screen_h,
        framebuf.MONO_HLSB
    )

    spi = SoftSPI(
        baudrate=2000000,
        polarity=0,
        phase=0,
        sck=Pin(13),
        mosi=Pin(14),
        miso=Pin(12),
    )

    cs = Pin(15)
    dc = Pin(27)
    rst = Pin(26)
    busy = Pin(25)

    epd_upload = EPD(spi, cs, dc, rst, busy)
    epd_upload.init()

    screen_fb.fill(0xFF)
    screen_fb.text("-- UPLOAD --", padding, padding, 0x00)
    screen_fb.hline(
        padding,
        padding + char_h + 4,
        screen_w - padding * 2,
        0x00
    )

    y = padding + char_h * 3
    screen_fb.text("WiFi: {}".format(WIFI_SSID), padding, y, 0x00)
    y += char_h + 8

    if ip:
        screen_fb.text("Open:", padding, y, 0x00)
        y += char_h + 8
        screen_fb.text("http://{}".format(ip), padding, y, 0x00)
    else:
        screen_fb.text("WiFi FAILED", padding, y, 0x00)
        y += char_h + 8
        screen_fb.text("Reset and try again", padding, y, 0x00)

    y += char_h + 12
    screen_fb.text("Upload .txt only", padding, y, 0x00)
    screen_fb.text("Reset when done", padding, screen_h - char_h - 4, 0x00)

    # Use no-prev display if you added it.
    try:
        epd_upload.display_frame_no_prev(screen_buf)
    except AttributeError:
        epd_upload.display_frame(screen_buf)

    gc.collect()
    profile_memory("before upload server")

    if ip:
        upload_server.start_upload_server(
            ssid=WIFI_SSID,
            password=WIFI_PASSWORD,
            book_dir="/library",
            max_file_size=UPLOAD_MAX_FILE_SIZE
        )
    else:
        while True:
            sleep_ms(1000)


rtc = machine.RTC()

if rtc.memory() == UPLOAD_BOOT_FLAG:
    rtc.memory(b"")
    run_upload_boot_mode()

import sprites
import upload_server
import _thread

# ── Startup behavior ──────────────────────────────────────────────────────────
START_IN_LOW_POWER_MODE = True

# ── Refresh policy ────────────────────────────────────────────────────────────
READ_FULL_REFRESH_EVERY = 8
WALK_FULL_REFRESH_EVERY = 12

read_refresh_count = 0
walk_refresh_count = 0

# ── Storage / NVS ─────────────────────────────────────────────────────────────
NVS_NAMESPACE = "tenku"
STEP_TOTAL_KEY = "st_t"
STEP_TODAY_KEY = "st_d"
STEP_DAY_KEY = "st_day"
TIME_KEY = "tm"
DATE_KEY = "dt"

PET_REG_KEY = "reg"
PET_REG_DEFAULT = 20260301 # March 1, 2026
CURRENT_BOOK_KEY = "current_book"
BOOK_DIR = "/library"
FALLBACK_BOOK_PATH = "/sample.txt"
FALLBACK_BOOK_NAME = "sample.txt"

# ── Display config ────────────────────────────────────────────────────────────
SCREEN_W = 400
SCREEN_H = 300
PADDING = 8

# Updated after config loads
CHAR_W = 10
CHAR_H = 10

TEXT_W = SCREEN_W - (PADDING * 2)
TEXT_H = SCREEN_H - (PADDING * 2)

COLS = TEXT_W // CHAR_W
ROWS = TEXT_H // CHAR_H

BUF_SIZE = SCREEN_W * SCREEN_H // 8

# Main full-screen draw buffer: 400 * 300 / 8 = 15000 bytes
SCREEN_BUF = bytearray(BUF_SIZE)
SCREEN_FB = framebuf.FrameBuffer(
    SCREEN_BUF,
    SCREEN_W,
    SCREEN_H,
    framebuf.MONO_HLSB
)

# ── Sprite / walk page layout ─────────────────────────────────────────────────
SPR_W = sprites.SPRITE_W
SPR_H = sprites.SPRITE_H

WALK_FRAMES = [sprites.WALK_0, sprites.WALK_1]
HEART_FULL_FRAME = sprites.HEART_FULL
HEART_EMPTY_FRAME = sprites.HEART_EMPTY
HUNGER_FULL_FRAME = sprites.HUNGER_FULL
HUNGER_EMPTY_FRAME = sprites.HUNGER_EMPTY

SPR_X = (SCREEN_W // 2 - SPR_W) // 2
SPR_Y = (SCREEN_H - SPR_H) // 2
STEP_TEXT_X = SCREEN_W // 2 + 16
STEP_TEXT_Y = (SCREEN_H - CHAR_H) // 2
_walk_frame = 0

STEP_WIN_W = 136
STEP_WIN_H = CHAR_H * 2 + 4
STEP_WIN_X = STEP_TEXT_X
STEP_WIN_Y = STEP_TEXT_Y - 2
STEP_WIN_BUF = bytearray((STEP_WIN_W // 8) * STEP_WIN_H)
STEP_WIN_FB = framebuf.FrameBuffer(STEP_WIN_BUF, STEP_WIN_W, STEP_WIN_H, framebuf.MONO_HLSB)

# ── Button helper ─────────────────────────────────────────────────────────────
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

        while self.pin.value() == 0:
            held = time.ticks_diff(time.ticks_ms(), t_down)
            if held >= self.long_press_ms:
                while self.pin.value() == 0:
                    sleep_ms(20)
                return "long"
            sleep_ms(10)

        return "short"

# ── SPI / display init ────────────────────────────────────────────────────────
spi = SoftSPI(
    baudrate=2000000,
    polarity=0,
    phase=0,
    sck=Pin(13),
    mosi=Pin(14),
    miso=Pin(12),
)
cs = Pin(15)
dc = Pin(27)
rst = Pin(26)
busy = Pin(25)

print("Initialising display...")
epd = EPD(spi, cs, dc, rst, busy)
epd.init()
epd.clear()
print("Display ready.")

# ── Button init ───────────────────────────────────────────────────────────────
btn_next_pin = Pin(32, Pin.IN, Pin.PULL_UP)
btn_prev_pin = Pin(33, Pin.IN, Pin.PULL_UP)
btn_settings_pin = Pin(4, Pin.IN, Pin.PULL_UP)

# NEXT long press = sleep. Set to 3000ms for 3-second hold.
next_btn = Button(btn_next_pin, debounce_ms=200, long_press_ms=3000)
prev_btn = Button(btn_prev_pin, debounce_ms=200, long_press_ms=700)
settings_btn = Button(btn_settings_pin, debounce_ms=200, long_press_ms=700)

# ── I2C / LSM6DS3 init ────────────────────────────────────────────────────────
i2c = I2C(0, scl=Pin(22), sda=Pin(21), freq=400000)

LSM6DS3_ADDR = 0x6B
LSM6DS3_WHO_AM_I = 0x0F
LSM6DS3_CTRL1_XL = 0x10
LSM6DS3_STEP_CTR_L = 0x4B
LSM6DS3_STEP_CTR_H = 0x4C
LSM6DS3_TAP_CFG = 0x58
LSM6DS3_CTRL10_C = 0x19


def lsm6ds3_init():
    try:
        who = i2c.readfrom_mem(LSM6DS3_ADDR, LSM6DS3_WHO_AM_I, 1)
        print("LSM6DS3 WHO_AM_I: 0x{:02X}".format(who[0]))
        i2c.writeto_mem(LSM6DS3_ADDR, LSM6DS3_CTRL1_XL, bytes([0x20]))
        i2c.writeto_mem(LSM6DS3_ADDR, LSM6DS3_TAP_CFG, bytes([0x40]))
        i2c.writeto_mem(LSM6DS3_ADDR, LSM6DS3_CTRL10_C, bytes([0x04]))
        print("LSM6DS3 pedometer enabled.")
        return True
    except Exception as e:
        print("LSM6DS3 init failed:", e)
        print("I2C devices:", i2c.scan())
        return False


def lsm6ds3_steps():
    try:
        data = i2c.readfrom_mem(LSM6DS3_ADDR, LSM6DS3_STEP_CTR_L, 2)
        return data[0] | (data[1] << 8)
    except Exception as e:
        print("LSM6DS3 read failed:", e)
        print("I2C devices:", i2c.scan())
        return -1
    
# ── Time Helpers ─────────────────────────────────────────────────────────────────
    
def today_yyyymmdd():
    now = time.localtime()
    return now[0] * 10000 + now[1] * 100 + now[2]


def ymd_to_days(y, m, d):
    # Days since 0000-03-01 style count.
    # Good enough for date differences.
    if m <= 2:
        y -= 1
        m += 12

    return 365 * y + y // 4 - y // 100 + y // 400 + ((153 * (m - 3) + 2) // 5) + d - 1


def yyyymmdd_to_days(v):
    y = v // 10000
    m = (v // 100) % 100
    d = v % 100
    return ymd_to_days(y, m, d)


def pet_alive_days():
    reg = PET_CONFIG.get("registered", PET_REG_DEFAULT)
    today = today_yyyymmdd()
    return max(0, yyyymmdd_to_days(today) - yyyymmdd_to_days(reg))

# ── Pet config ─────────────────────────────────────────────────────────────

PET_NAME_MAX_LEN = 5
PET_NAME_CHARS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ "
PET_NAME_KEY = "pet_name"
PET_HEARTS_KEY = "pet_hearts"
PET_HUNGER_KEY = "pet_hunger"

PET_CONFIG = {
    "nickname": "TENKU",
    "hearts": 5,
    "hunger": 100,
    "registered": PET_REG_DEFAULT,
}

SPRITE_AREA_W = 160
SPRITE_AREA_H = 160
SPRITE_AREA_X = SPR_X + (SPR_W - SPRITE_AREA_W) // 2
SPRITE_AREA_Y = SPR_Y - 48

SPRITE_AREA_BUF = bytearray((SPRITE_AREA_W // 8) * SPRITE_AREA_H)
SPRITE_AREA_FB = framebuf.FrameBuffer(
    SPRITE_AREA_BUF,
    SPRITE_AREA_W,
    SPRITE_AREA_H,
    framebuf.MONO_HLSB
)

# ── Device config ─────────────────────────────────────────────────────────────
TEMP_CONFIG = {}
CONFIG = {
    "font_size": 10,
    "current_time": "12:00",
    "current_date": "2026-04-28",
}
CONFIG_READONLY = {
    "ram_used": 0,
    "ram_total": 0,
    "flash_used": 0,
    "flash_available": 0,
}
DEVICE_CONFIG_OPTIONS = [
    ("font_size", 10),
    ("pet_nickname", "TENKU"),
    ("current_date", "2026-04-28"),
    ("current_time", "12:00"),
]
DEVICE_CONFIG_ACTIONS = ["SAVE", "CANCEL"]
READONLY_FIELDS = [
    ("ram_used", "RAM"),
    ("flash_used", "Flash"),
]

time_char_idx = 0
date_char_idx = 0

def begin_config_edit():
    global TEMP_CONFIG
    TEMP_CONFIG = CONFIG.copy()
    TEMP_CONFIG["pet_nickname"] = PET_CONFIG["nickname"]
    TEMP_CONFIG["current_time"] = CONFIG.get("current_time", "12:00")
    TEMP_CONFIG["current_date"] = CONFIG.get("current_date", "2026-04-28")

def discard_config_edit():
    global TEMP_CONFIG
    TEMP_CONFIG = {}

def commit_config_edit():
    global TEMP_CONFIG, CONFIG

    if "font_size" in TEMP_CONFIG:
        CONFIG["font_size"] = TEMP_CONFIG["font_size"]

    if "pet_nickname" in TEMP_CONFIG:
        PET_CONFIG["nickname"] = TEMP_CONFIG["pet_nickname"][:PET_NAME_MAX_LEN].strip()
        save_pet_config()
        
    if "current_time" in TEMP_CONFIG:
        CONFIG["current_time"] = TEMP_CONFIG["current_time"]
        apply_config_time()
        
    if "current_date" in TEMP_CONFIG:
        CONFIG["current_date"] = TEMP_CONFIG["current_date"]

    apply_config_datetime()

    TEMP_CONFIG = {}
    save_config()

def update_readonly_fields():
    gc.collect()
    free = gc.mem_free()
    alloc = gc.mem_alloc()
    CONFIG_READONLY["ram_used"] = alloc
    CONFIG_READONLY["ram_total"] = free + alloc

    try:
        stat = os.statvfs("/")
        block_size = stat[0]
        available_blocks = stat[3]
        total_blocks = stat[2]
        CONFIG_READONLY["flash_available"] = available_blocks * block_size
        CONFIG_READONLY["flash_used"] = (total_blocks - available_blocks) * block_size
    except Exception as e:
        print("Flash stat failed:", e)
        CONFIG_READONLY["flash_used"] = 0
        CONFIG_READONLY["flash_available"] = 0

def get_char_dimensions():
    font_size = CONFIG.get("font_size", 10)
    return font_size, font_size

def load_config():
    try:
        nvs = esp32.NVS(NVS_NAMESPACE)

        try:
            CONFIG["font_size"] = nvs.get_i32("font_size")
            print("Loaded font_size:", CONFIG["font_size"])
        except OSError:
            print("font_size not found; using default:", CONFIG["font_size"])

        try:
            time_val = nvs.get_i32(TIME_KEY)
            hour = time_val // 100
            minute = time_val % 100

            if 0 <= hour <= 23 and 0 <= minute <= 59:
                CONFIG["current_time"] = "{:02d}:{:02d}".format(hour, minute)
                print("Loaded time:", CONFIG["current_time"])
        except OSError:
            print("time not found; using default:", CONFIG["current_time"])

        try:
            date_val = nvs.get_i32(DATE_KEY)
            year = date_val // 10000
            month = (date_val // 100) % 100
            day = date_val % 100

            if 2020 <= year <= 2099 and 1 <= month <= 12 and 1 <= day <= 31:
                CONFIG["current_date"] = "{:04d}-{:02d}-{:02d}".format(
                    year,
                    month,
                    day
                )
                print("Loaded date:", CONFIG["current_date"])
        except OSError:
            print("date not found; using default:", CONFIG["current_date"])

        apply_config_datetime()

    except Exception as e:
        print("NVS open failed:", e)
        
def save_config():
    try:
        nvs = esp32.NVS(NVS_NAMESPACE)

        nvs.set_i32("font_size", CONFIG["font_size"])

        # Save HH:MM as integer HHMM
        time_str = CONFIG.get("current_time", "12:00")
        try:
            hour = int(time_str[0:2])
            minute = int(time_str[3:5])
            time_val = hour * 100 + minute
        except Exception:
            time_val = 1200

        # Save YYYY-MM-DD as integer YYYYMMDD
        date_str = CONFIG.get("current_date", "2026-04-28")
        try:
            year = int(date_str[0:4])
            month = int(date_str[5:7])
            day = int(date_str[8:10])
            date_val = year * 10000 + month * 100 + day
        except Exception:
            date_val = 20260428

        nvs.set_i32(TIME_KEY, time_val)
        nvs.set_i32(DATE_KEY, date_val)

        nvs.commit()
        print("Config saved to NVS")
        print("Saved time:", time_val)
        print("Saved date:", date_val)

    except Exception as e:
        print("NVS save failed:", e)

def adjust_config_value(key, direction):
    global device_name_char_idx

    if key == "font_size":
        current = TEMP_CONFIG.get(key, CONFIG.get(key))
        TEMP_CONFIG[key] = max(8, min(16, current + direction))

    elif key == "pet_nickname":
        name = TEMP_CONFIG.get("pet_nickname", PET_CONFIG["nickname"])
        name = (name + " " * PET_NAME_MAX_LEN)[:PET_NAME_MAX_LEN]

        current_char = name[device_name_char_idx]
        char_idx = PET_NAME_CHARS.find(current_char)

        if char_idx < 0:
            char_idx = 0

        char_idx = (char_idx + direction) % len(PET_NAME_CHARS)

        chars = list(name)
        chars[device_name_char_idx] = PET_NAME_CHARS[char_idx]

        TEMP_CONFIG["pet_nickname"] = "".join(chars).rstrip()
    elif key == "current_time":
        time_str = TEMP_CONFIG.get("current_time", CONFIG.get("current_time", "12:00"))

        try:
            hour = int(time_str[:2])
            minute = int(time_str[3:5])
        except Exception:
            hour = 12
            minute = 0

        hour_tens = hour // 10
        hour_ones = hour % 10
        min_tens = minute // 10
        min_ones = minute % 10

        if time_char_idx == 0:
            hour_tens = (hour_tens + direction) % 3
        elif time_char_idx == 1:
            hour_ones = (hour_ones + direction) % 10
        elif time_char_idx == 3:
            min_tens = (min_tens + direction) % 6
        elif time_char_idx == 4:
            min_ones = (min_ones + direction) % 10

        hour = hour_tens * 10 + hour_ones
        if hour > 23:
            hour = 23

        minute = min_tens * 10 + min_ones

        TEMP_CONFIG["current_time"] = "{:02d}:{:02d}".format(hour, minute)

    elif key == "current_date":
        date_str = TEMP_CONFIG.get(
            "current_date",
            CONFIG.get("current_date", "2026-04-28")
        )

        chars = list(date_str)

        if len(chars) != 10:
            chars = list("2026-04-28")

        if date_char_idx in (0, 1, 2, 3, 5, 6, 8, 9):
            current_digit = chars[date_char_idx]

            if current_digit < "0" or current_digit > "9":
                current_digit = "0"

            new_digit = (int(current_digit) + direction) % 10
            chars[date_char_idx] = str(new_digit)

        TEMP_CONFIG["current_date"] = "".join(chars)

def load_pet_config():
    try:
        nvs = esp32.NVS(NVS_NAMESPACE)

        try:
            name = ""
            for i in range(PET_NAME_MAX_LEN):
                idx = nvs.get_i32(PET_NAME_KEY + str(i))
                if 0 <= idx < len(PET_NAME_CHARS):
                    name += PET_NAME_CHARS[idx]
                else:
                    name += " "

            PET_CONFIG["nickname"] = name.rstrip()
        except Exception:
            pass

        try:
            PET_CONFIG["hearts"] = nvs.get_i32(PET_HEARTS_KEY)
        except Exception:
            pass

        try:
            PET_CONFIG["hunger"] = nvs.get_i32(PET_HUNGER_KEY)
        except Exception:
            pass
        
        try:
            PET_CONFIG["registered"] = nvs.get_i32(PET_REG_KEY)
        except Exception:
            PET_CONFIG["registered"] = PET_REG_DEFAULT
            try:
                nvs.set_i32(PET_REG_KEY, PET_REG_DEFAULT)
                nvs.commit()
            except Exception:
                pass

    except Exception as e:
        print("Pet config load failed:", e)


def save_pet_config():
    try:
        nvs = esp32.NVS(NVS_NAMESPACE)
        name = PET_CONFIG["nickname"]
        name = (name + " " * PET_NAME_MAX_LEN)[:PET_NAME_MAX_LEN]

        for i, ch in enumerate(name):
            idx = PET_NAME_CHARS.find(ch)

            if idx < 0:
                idx = PET_NAME_CHARS.find(" ")

            nvs.set_i32(PET_NAME_KEY + str(i), idx)
        nvs.set_i32(PET_HEARTS_KEY, PET_CONFIG["hearts"])
        nvs.set_i32(PET_HUNGER_KEY, PET_CONFIG["hunger"])
        nvs.set_i32(PET_REG_KEY, PET_CONFIG["registered"])
        nvs.commit()
        print("Pet config saved")
    except Exception as e:
        print("Pet config save failed:", e)

def recalculate_pagination():
    global COLS, ROWS
    COLS = TEXT_W // CHAR_W
    ROWS = TEXT_H // CHAR_H
    print("Pagination updated: {} cols x {} rows".format(COLS, ROWS))

# ── Book list / page memory ───────────────────────────────────────────────────
def ensure_book_dir():
    try:
        os.mkdir(BOOK_DIR)
    except OSError:
        pass


def list_library():
    ensure_book_dir()
    try:
        files = os.listdir(BOOK_DIR)
        library = [f for f in files if f.endswith(".txt")]
        library.sort()
        return library
    except Exception as e:
        print("list_library failed:", e)
        return []


def book_key_hash(filename):
    total = 0
    for ch in filename:
        total = (total * 31 + ord(ch)) % 1000000
    return str(total)


def offset_key_for_book(filename):
    return "off_" + book_key_hash(filename)


def load_book_offset(filename):
    try:
        nvs = esp32.NVS(NVS_NAMESPACE)
        return nvs.get_i32(offset_key_for_book(filename))
    except OSError:
        return 0
    except Exception as e:
        print("load_book_offset failed:", e)
        return 0


def save_book_offset(filename, offset):
    try:
        nvs = esp32.NVS(NVS_NAMESPACE)
        nvs.set_i32(offset_key_for_book(filename), int(offset))
        nvs.commit()
        print("Saved offset {} for {}".format(offset, filename))
    except Exception as e:
        print("save_book_offset failed:", e)


def load_current_book():
    library = list_library()
    if not library:
        return None

    try:
        nvs = esp32.NVS(NVS_NAMESPACE)
        saved_idx = nvs.get_i32(CURRENT_BOOK_KEY)
        if 0 <= saved_idx < len(library):
            return library[saved_idx]
    except Exception:
        pass

    return library[0]


def save_current_book_index(filename):
    library = list_library()
    try:
        idx = library.index(filename)
        nvs = esp32.NVS(NVS_NAMESPACE)
        nvs.set_i32(CURRENT_BOOK_KEY, idx)
        nvs.commit()
        print("Saved current book:", filename)
    except Exception as e:
        print("save_current_book_index failed:", e)

# ── Steps NVS ─────────────────────────────────────────────────────────────────
def load_step_state():
    today = today_yyyymmdd()

    total = 0
    today_steps = 0
    saved_day = today

    try:
        nvs = esp32.NVS(NVS_NAMESPACE)

        try:
            total = nvs.get_i32(STEP_TOTAL_KEY)
        except OSError:
            total = 0

        try:
            today_steps = nvs.get_i32(STEP_TODAY_KEY)
        except OSError:
            today_steps = 0

        try:
            saved_day = nvs.get_i32(STEP_DAY_KEY)
        except OSError:
            saved_day = today

        if saved_day != today:
            today_steps = 0
            saved_day = today
            save_steps_to_nvs(total, today_steps, saved_day)

    except Exception as e:
        print("Step state load failed:", e)

    return total, today_steps, saved_day


def save_steps_to_nvs(total_steps, today_steps, step_day):
    try:
        nvs = esp32.NVS(NVS_NAMESPACE)
        nvs.set_i32(STEP_TOTAL_KEY, total_steps)
        nvs.set_i32(STEP_TODAY_KEY, today_steps)
        nvs.set_i32(STEP_DAY_KEY, step_day)
        nvs.commit()
        print("Saved steps total={} today={}".format(total_steps, today_steps))
    except Exception as e:
        print("Step NVS save failed:", e)

# ── Streaming text pagination ────────────────────────────────────────────────
def get_book_size(filepath):
    try:
        return os.stat(filepath)[6]
    except Exception as e:
        print("get_book_size failed:", e)
        return 0


def content_rows():
    # Keep one row free for the progress indicator.
    return max(1, ROWS - 1)


def normalize_line(raw):
    # Keep paragraph/newline boundaries as spaces without creating a giant string.
    return raw.replace("\r", " ").replace("\n", " ").replace("\t", " ")


def wrap_text_line(raw):
    line = normalize_line(raw)
    words = [w for w in line.split(" ") if w]
    wrapped = []
    current_line = ""

    if not words:
        return [""]

    for word in words:
        while len(word) > COLS:
            head = word[:COLS]
            word = word[COLS:]
            if current_line:
                wrapped.append(current_line)
                current_line = ""
            wrapped.append(head)

        tentative = word if current_line == "" else current_line + " " + word

        if len(tentative) <= COLS:
            current_line = tentative
        else:
            if current_line:
                wrapped.append(current_line)
            current_line = word

    if current_line:
        wrapped.append(current_line)

    return wrapped if wrapped else [""]


def read_page(filepath, start_offset):
    """
    RAM-safe page reader.

    It reads from a byte offset, wraps only enough text to fill the screen,
    and returns the next offset instead of building/storing all pages.
    """
    gc.collect()

    size = get_book_size(filepath)
    if size <= 0:
        return ["No text found."], 0, 0, 0

    if start_offset < 0:
        start_offset = 0
    if start_offset >= size:
        start_offset = max(0, size - 1)

    lines = []
    next_offset = start_offset
    max_rows = content_rows()

    with open(filepath, "r") as f:
        f.seek(start_offset)

        while len(lines) < max_rows:
            line_start = f.tell()
            raw = f.readline()

            if not raw:
                next_offset = f.tell()
                break

            wrapped = wrap_text_line(raw)

            for wrapped_line in wrapped:
                if len(lines) >= max_rows:
                    # We did not consume this source line visually, so restart
                    # from the beginning of that line on the next page.
                    next_offset = line_start
                    gc.collect()
                    return lines, start_offset, next_offset, size
                lines.append(wrapped_line)

            next_offset = f.tell()

    gc.collect()
    return lines, start_offset, next_offset, size


def find_previous_offset(filepath, current_offset):
    """
    Finds the previous page without storing a full page table.

    It backs up by a rough estimate, then repeatedly calls read_page()
    until it finds the page immediately before current_offset.
    """
    if current_offset <= 0:
        return 0

    approx_chars_per_page = max(1, content_rows() * COLS)
    search_start = max(0, current_offset - approx_chars_per_page * 3)

    candidate = search_start
    previous = search_start

    while True:
        _, page_start, next_offset, _ = read_page(filepath, candidate)

        if next_offset >= current_offset or next_offset == candidate:
            return previous

        previous = page_start
        candidate = next_offset


def load_current_page(filepath, offset):
    page_lines, actual_offset, next_offset, book_size = read_page(filepath, offset)
    return page_lines, actual_offset, next_offset, book_size


def count_total_pages(filepath):
    """
    Counts pages without storing them.

    This is slower than the old build_pages(), but it is RAM-safe because it
    only streams one page at a time. It also respects the current font/layout.
    """
    gc.collect()

    size = get_book_size(filepath)
    if size <= 0:
        return 1

    count = 0
    offset = 0

    while True:
        _, actual_offset, next_offset, _ = read_page(filepath, offset)
        count += 1

        if next_offset <= actual_offset or next_offset >= size:
            break

        offset = next_offset

    gc.collect()
    return max(1, count)


def page_num_from_offset(filepath, target_offset):
    """
    Finds the 0-based page number for a byte offset without storing pages.
    Used on startup/book switch/font change to restore page numbering.
    """
    if target_offset <= 0:
        return 0

    gc.collect()

    page_num = 0
    offset = 0

    while True:
        _, actual_offset, next_offset, _ = read_page(filepath, offset)

        if actual_offset >= target_offset or next_offset > target_offset or next_offset <= actual_offset:
            break

        page_num += 1
        offset = next_offset

    gc.collect()
    return page_num

# ── Frame building / rendering ────────────────────────────────────────────────
def build_frame(page_lines, page_num, total_pages):
    fb = SCREEN_FB
    fb.fill(0xFF)

    for row_idx, line in enumerate(page_lines):
        if row_idx >= content_rows():
            break
        fb.text(line, PADDING, PADDING + (row_idx * CHAR_H), 0x00)

    indicator = "{}/{}".format(page_num + 1, total_pages)

    fb.text(
        indicator,
        SCREEN_W - PADDING - (len(indicator) * CHAR_W),
        SCREEN_H - CHAR_H - 2,
        0x00,
    )

    return SCREEN_BUF

def draw_datetime_header(fb):
    now = time.localtime()
    hour = now[3]
    minute = now[4]
    am_pm = "AM" if hour < 12 else "PM"

    hour_12 = hour % 12
    if hour_12 == 0:
        hour_12 = 12

    time_str = "{:d}:{:02d} {}".format(hour_12, minute, am_pm)
    x = SCREEN_W - PADDING - (len(time_str) * 8)
    y = PADDING
    fb.text(time_str, x, y, 0x00)
    
def days_in_month(year, month):
    if month in (1, 3, 5, 7, 8, 10, 12):
        return 31
    elif month in (4, 6, 9, 11):
        return 30
    elif month == 2:
        # leap year check
        if (year % 4 == 0 and year % 100 != 0) or (year % 400 == 0):
            return 29
        return 28
    return 31
    
def apply_config_time():
    time_str = CONFIG.get("current_time", "12:00")

    try:
        hour = int(time_str[:2])
        minute = int(time_str[3:5])
    except Exception:
        return

    now = time.localtime()

    # machine.RTC datetime format:
    # (year, month, day, weekday, hour, minute, second, subseconds)
    rtc = machine.RTC()
    rtc.datetime((
        now[0],
        now[1],
        now[2],
        now[6],
        hour,
        minute,
        0,
        0
    ))
    
def apply_config_datetime():
    date_str = CONFIG.get("current_date", "2026-04-28")
    time_str = CONFIG.get("current_time", "12:00")

    try:
        year = int(date_str[0:4])
        month = int(date_str[5:7])
        day = int(date_str[8:10])

        hour = int(time_str[0:2])
        minute = int(time_str[3:5])
    except Exception:
        return

    rtc = machine.RTC()

    # MicroPython RTC format:
    # (year, month, day, weekday, hour, minute, second, subseconds)
    rtc.datetime((year, month, day, 0, hour, minute, 0, 0))

def render_page(page_lines, page_num, total_pages, full=False):
    mode_name = "full" if full else "partial"
    print("\n--- render_page {}/{} ({}) ---".format(page_num + 1, total_pages, mode_name))

    t0 = time.ticks_ms()
    buf = build_frame(page_lines, page_num, total_pages)
    print("[TIME] build_frame {}ms".format(time.ticks_diff(time.ticks_ms(), t0)))

    t0 = time.ticks_ms()
    if full:
        epd.display_frame(buf)
    else:
        epd.display_frame_partial(buf)
    print("[TIME] display write+wait {}ms".format(time.ticks_diff(time.ticks_ms(), t0)))

    gc.collect()


def render_page_hybrid(page_lines, page_num, total_pages, force_full=False):
    # RAM-safe version: no quick_white_clear allocation.
    # Use partial normally, full only when forced or every N page turns.
    global read_refresh_count
    read_refresh_count += 1
    use_full = force_full or (read_refresh_count % READ_FULL_REFRESH_EVERY == 0)
    render_page(page_lines, page_num, total_pages, full=use_full)

# ── Settings page ─────────────────────────────────────────────────────────────
SETTINGS_OPTIONS = ["READ", "WALK", "LIBRARY", "DEVICE"]


def render_settings(selected_idx, full=False):
    fb = SCREEN_FB
    fb.fill(0xFF)

    title = "HOME"
    fb.text(title, PADDING, PADDING, 0x00)
    draw_datetime_header(fb)
    fb.hline(PADDING, PADDING + CHAR_H + 4, SCREEN_W - PADDING * 2, 0x00)

    for i, option in enumerate(SETTINGS_OPTIONS):
        y = PADDING + CHAR_H * 3 + i * (CHAR_H + 6)
        cursor = "> " if i == selected_idx else "  "
        fb.text(cursor + option, PADDING, y, 0x00)

    hint = "UP/DN: navigate SET: select"
    fb.text(hint, PADDING, SCREEN_H - CHAR_H - 4, 0x00)

    # One-buffer mode: always use no-prev full refresh for this screen.
    epd.display_frame_no_prev(SCREEN_BUF)

    gc.collect()
    
# ── Books page ────────────────────────────────────────────────────────────────
def render_library(book_idx, full=False):
    library = list_library()

    fb = SCREEN_FB
    fb.fill(0xFF)

    title = "LIBRARY"
    fb.text(title, PADDING, PADDING, 0x00)
    draw_datetime_header(fb)
    fb.hline(PADDING, PADDING + CHAR_H + 4, SCREEN_W - PADDING * 2, 0x00)

    y = PADDING + CHAR_H * 3

    if not library:
        fb.text("No .txt files found", PADDING, y, 0x00)
        fb.text("Add files to /library", PADDING, y + CHAR_H + 6, 0x00)
    else:
        max_visible = (SCREEN_H - y - CHAR_H * 3) // (CHAR_H + 6)
        if max_visible < 1:
            max_visible = 1

        start = 0
        if book_idx >= max_visible:
            start = book_idx - max_visible + 1

        visible_library = library[start:start + max_visible]
        max_name_len = (SCREEN_W - PADDING * 2) // CHAR_W - 2

        for i, book in enumerate(visible_library):
            actual_idx = start + i
            cursor = "> " if actual_idx == book_idx else "  "
            name = book
            if len(name) > max_name_len:
                name = name[:max_name_len - 3] + "..."
            fb.text(cursor + name, PADDING, y, 0x00)
            y += CHAR_H + 6

    hint = "UP/DN: choose SET: open LONG: menu"
    fb.text(hint, PADDING, SCREEN_H - CHAR_H - 4, 0x00)

    if full:
        epd.display_frame(SCREEN_BUF)
    else:
        epd.display_frame_partial(SCREEN_BUF)

    gc.collect()
    
def render_upload_page(full=True):
    fb = SCREEN_FB
    fb.fill(0xFF)

    title = "-- UPLOAD --"
    fb.text(title, PADDING, PADDING, 0x00)
    draw_datetime_header(fb)
    fb.hline(PADDING, PADDING + CHAR_H + 4, SCREEN_W - PADDING * 2, 0x00)

    y = PADDING + CHAR_H * 3
    fb.text("Website at: http://192.168.4.1", PADDING, y, 0x00)

    if full:
        epd.display_frame(SCREEN_BUF)
    else:
        epd.display_frame_partial(SCREEN_BUF)

    gc.collect()

# ── Device config page ────────────────────────────────────────────────────────
def render_device_config(selected_idx, editing_idx, full=False):
    update_readonly_fields()

    fb = SCREEN_FB
    fb.fill(0xFF)

    title = "DEVICE"
    fb.text(title, PADDING, PADDING, 0x00)
    draw_datetime_header(fb)
    fb.hline(PADDING, PADDING + CHAR_H + 4, SCREEN_W - PADDING * 2, 0x00)

    y = PADDING + CHAR_H * 3

    for key, label in READONLY_FIELDS:
        value = CONFIG_READONLY.get(key, 0)
        
        if key == "ram_used":
            used = gc.mem_alloc()
            total = gc.mem_alloc() + gc.mem_free()
            percent = int((used / total) * 100)
            line = "{}: {} / {} bytes ({}%)".format(label, used, total, percent)

        elif key == "flash_used":
            used = CONFIG_READONLY["flash_used"]
            total = CONFIG_READONLY["flash_used"] + CONFIG_READONLY["flash_available"]
            percent = int((used / total) * 100) if total else 0
            line = "{}: {} / {} bytes ({}%)".format(label, used, total, percent)
        
        elif key == "current_date":
            label = "Date"
            value_str = TEMP_CONFIG.get("current_date", CONFIG.get("current_date", "2026-04-28"))

        elif key == "current_time":
            label = "Time"
            value_str = TEMP_CONFIG.get("current_time", CONFIG.get("current_time", "12:00"))
        
        else:
            continue
                
        fb.text(line, PADDING, y, 0x00)
        y += CHAR_H + 6

    fb.hline(PADDING, y + PADDING , SCREEN_W - PADDING * 2, 0x00)
    y += CHAR_H + PADDING

    for i, (key, default) in enumerate(DEVICE_CONFIG_OPTIONS):
        is_selected = selected_idx == i
        is_editing = editing_idx == i
        value = TEMP_CONFIG.get(key, CONFIG.get(key, default))

        if key == "font_size":
            label = "Font Size"
            value_str = str(value) + "px"
        elif key == "pet_nickname":
            label = "Nickname"
            value = TEMP_CONFIG.get("pet_nickname", PET_CONFIG["nickname"])
            value_str = value
        elif key == "current_date":
            label = "Date"
            value_str = str(value)
        elif key == "current_time":
            label = "Time"
            value_str = str(value)
        else:
            label = key
            value_str = str(value)

        cursor = "> " if is_selected else "  "
        line = "{}{}: {}".format(cursor, label, value_str)

        if is_editing and key == "pet_nickname":
            prefix = cursor + label + ": "
            
            value_x = PADDING + (len(label) * CHAR_W)
            underline_x = value_x + (device_name_char_idx * (CHAR_W - 4))
            underline_y = y + CHAR_H

            fb.hline(underline_x, underline_y, CHAR_W // 2, 0x00)

        elif is_editing and key == "current_date":
            prefix = cursor + label + ": "
            value_x = PADDING + (len(prefix) * 8)
            underline_x = value_x + (date_char_idx * 8)
            underline_y = y + CHAR_H
            fb.hline(underline_x, underline_y, 8, 0x00)

        elif is_editing and key == "current_time":
            prefix = cursor + label + ": "
            value_x = PADDING + (len(prefix) * 8)
            underline_x = value_x + (time_char_idx * 8)
            underline_y = y + CHAR_H
            fb.hline(underline_x, underline_y, 8, 0x00)

        elif is_editing:
            key_start_x = PADDING + (len(cursor) * CHAR_W)
            key_width = len(label) * CHAR_W
            fb.hline(key_start_x - (CHAR_W // 2), y + CHAR_H, key_width - CHAR_W, 0x00)

        fb.text(line, PADDING, y, 0x00)
        y += CHAR_H + 6

    for i, action in enumerate(DEVICE_CONFIG_ACTIONS):
        action_idx = len(DEVICE_CONFIG_OPTIONS) + i
        is_selected = selected_idx == action_idx
        cursor = "> " if is_selected else "  "
        fb.text(cursor + action, PADDING, y, 0x00)
        y += CHAR_H + 6

    hint = "UP/DN: adjust SET: confirm" if editing_idx is not None else "UP/DN: navigate SET: edit"
    fb.text(hint, PADDING, SCREEN_H - CHAR_H - 4, 0x00)

    if full:
        epd.display_frame(SCREEN_BUF)
    else:
        epd.display_frame_partial(SCREEN_BUF)

    gc.collect()

# ── Walk page ─────────────────────────────────────────────────────────────────
def render_walk_page_full(steps):
    fb = SCREEN_FB
    fb.fill(0xFF)

    title = "WALK MODE"
    fb.text(title, PADDING, PADDING, 0x00)
    draw_datetime_header(fb)
    fb.hline(PADDING, PADDING + CHAR_H + 4, SCREEN_W - PADDING * 2, 0x00)
    fb.vline(
        SCREEN_W // 2,
        PADDING + CHAR_H + 8,
        SCREEN_H - PADDING * 2 - CHAR_H - 28,
        0x00,
    )
    fb.text("NEXT/PREV: refresh LONG SET: menu", PADDING, SCREEN_H - CHAR_H - 4, 0x00)

    epd.display_frame(SCREEN_BUF)
    gc.collect()

    _render_sprite_window(0)
    sleep_ms(300)
    render_walk_update(steps)


def _render_sprite_window(frame_idx):
    ICON_W = sprites.SPRITE_W
    ICON_H = sprites.SPRITE_H
    SPACING = -10
    NUM_ICONS = 3

    step_x = ICON_W + SPACING
    total_width = ICON_W + step_x * (NUM_ICONS - 1)

    SPRITE_AREA_FB.fill(0xFF)

    pet_x = (SPRITE_AREA_W - SPR_W) // 2
    pet_y = ICON_H + 8
    
    day_str = "Day {}".format(pet_alive_days())
    nickname = PET_CONFIG["nickname"]

    day_x = (SPRITE_AREA_W - (len(day_str) * 8)) // 2
    day_y = pet_y - (CHAR_H * 4)

    nick_x = (SPRITE_AREA_W - (len(nickname) * 8)) // 2
    nick_y = pet_y - (CHAR_H * 2)

    SPRITE_AREA_FB.text(day_str, day_x, day_y, 0x00)
    SPRITE_AREA_FB.text(nickname, nick_x, nick_y, 0x00)

    SPRITE_AREA_FB.text(nickname, nick_x, nick_y, 0x00)

    hearts_x = (SPRITE_AREA_W - total_width) // 2
    hearts_y = pet_y + SPR_H + 10

    hunger_x = hearts_x
    hunger_y = hearts_y + ICON_H - 15 + 10

    heart_fb = framebuf.FrameBuffer(
        HEART_FULL_FRAME,
        ICON_W,
        ICON_H,
        framebuf.MONO_HLSB
    )

    hunger_fb = framebuf.FrameBuffer(
        HUNGER_FULL_FRAME,
        ICON_W,
        ICON_H,
        framebuf.MONO_HLSB
    )

    pet_fb = framebuf.FrameBuffer(
        WALK_FRAMES[frame_idx],
        SPR_W,
        SPR_H,
        framebuf.MONO_HLSB
    )

    for i in range(NUM_ICONS):
        x = hearts_x + i * step_x
        SPRITE_AREA_FB.blit(heart_fb, x, hearts_y)
        SPRITE_AREA_FB.blit(hunger_fb, x, hunger_y)

    SPRITE_AREA_FB.blit(pet_fb, pet_x, pet_y)

    epd.display_frame_partial_window(
        SPRITE_AREA_BUF,
        SPRITE_AREA_X,
        SPRITE_AREA_Y,
        SPRITE_AREA_W,
        SPRITE_AREA_H
    )

    gc.collect()

def _render_step_window(steps):
    fb = STEP_WIN_FB
    fb.fill(0xFF)

    total_str = "Total Steps: {}".format(saved_steps)
    today_str = "Today: {}".format(today_steps)

    # pixel width (8px per char)
    total_w = len(total_str) * 8
    today_w = len(today_str) * 8

    # center horizontally
    total_x = (STEP_WIN_W - total_w) // 2
    today_x = (STEP_WIN_W - today_w) // 2

    # vertical positioning (center both lines)
    total_y = (STEP_WIN_H // 2) - (2 * CHAR_H)
    today_y = (STEP_WIN_H // 2) + (2 * CHAR_H)

    fb.text(total_str, total_x, total_y, 0x00)
    fb.text(today_str, today_x, today_y, 0x00)

    epd.display_frame_partial_window(
        STEP_WIN_BUF,
        STEP_WIN_X,
        STEP_WIN_Y,
        STEP_WIN_W,
        STEP_WIN_H
    )

def render_walk_update(steps):
    global _walk_frame
    _walk_frame = (_walk_frame + 1) % len(WALK_FRAMES)
    _render_sprite_window(_walk_frame)
    _render_step_window(steps)


def render_walk_update_hybrid(steps):
    global walk_refresh_count
    walk_refresh_count += 1

    if walk_refresh_count % WALK_FULL_REFRESH_EVERY == 0:
        render_walk_page_full(steps)
    else:
        render_walk_update(steps)

# ── Misc helpers ──────────────────────────────────────────────────────────────
def center_text(text):
    x = (SCREEN_W - len(text) * CHAR_W) // 2
    y = (SCREEN_H - CHAR_H) // 2
    return x, y


def update_total_steps():
    global saved_steps, today_steps, step_day, last_sensor_steps

    current_day = today_yyyymmdd()

    if current_day != step_day:
        today_steps = 0
        step_day = current_day
        save_steps_to_nvs(saved_steps, today_steps, step_day)

    sensor_steps = lsm6ds3_steps()

    if sensor_steps >= 0 and last_sensor_steps >= 0:
        delta = sensor_steps - last_sensor_steps

        if delta < 0:
            delta = sensor_steps

        if delta > 0:
            saved_steps += delta
            today_steps += delta
            last_sensor_steps = sensor_steps
            save_steps_to_nvs(saved_steps, today_steps, step_day)

    return saved_steps

# ── Low power ─────────────────────────────────────────────────────────────────
WAKE_PIN = btn_next_pin


def enter_low_power_mode():
    print("Entering low power mode...")

    fb = SCREEN_FB
    fb.fill(0x00)
    start_txt = "TENKU"
    center_x, center_y = center_text(start_txt)
    fb.text(start_txt, center_x, center_y, 0xFF)
    epd.display_frame_no_prev(SCREEN_BUF)
    gc.collect()

    epd.sleep()

    try:
        i2c.writeto_mem(LSM6DS3_ADDR, LSM6DS3_CTRL1_XL, bytes([0x00]))
        i2c.writeto_mem(LSM6DS3_ADDR, LSM6DS3_CTRL10_C, bytes([0x00]))
    except Exception as e:
        print("Sensor sleep failed:", e)

    while btn_next_pin.value() == 0:
        sleep_ms(20)

    sleep_ms(200)
    esp32.wake_on_ext0(pin=WAKE_PIN, level=esp32.WAKEUP_ALL_LOW)

    print("Deep sleeping. Press NEXT button to wake...")
    sleep_ms(500)
    machine.deepsleep()

# ── App modes ─────────────────────────────────────────────────────────────────
MODE_READ = "read"
MODE_WALK = "walk"
MODE_SETTINGS = "settings"
MODE_DEVICE = "device"
MODE_LIBRARY = "library"

# ── Startup ───────────────────────────────────────────────────────────────────
print("=== STARTUP ===")
profile_memory("startup")

accel_ok = lsm6ds3_init()

print("Wake reason:", machine.wake_reason())

if machine.wake_reason() == 0:
    if START_IN_LOW_POWER_MODE:
        print("Fresh boot. Entering low power mode...")
        enter_low_power_mode()
else:
    print("Woke from deep sleep. Reinitializing display...")
    epd.init()

print("Loading config from NVS...")
load_config()
load_pet_config()
apply_config_datetime()

CHAR_W, CHAR_H = get_char_dimensions()
COLS = TEXT_W // CHAR_W
ROWS = TEXT_H // CHAR_H
print("Font size: {}px".format(CONFIG["font_size"]))
print("Pagination: {} cols x {} rows".format(COLS, ROWS))

ensure_book_dir()

current_book = load_current_book()
if current_book is None:
    current_book = FALLBACK_BOOK_NAME
    current_book_path = FALLBACK_BOOK_PATH
else:
    current_book_path = BOOK_DIR + "/" + current_book

print("Loading current page for:", current_book_path)
current_offset = load_book_offset(current_book) if current_book is not None else 0
page_lines, current_offset, next_offset, book_size = load_current_page(current_book_path, current_offset)
print("Counting pages for current layout...")
total_pages = count_total_pages(current_book_path)
current_page = page_num_from_offset(current_book_path, current_offset)
if current_page >= total_pages:
    current_page = max(0, total_pages - 1)
print("Page: {}/{}".format(current_page + 1, total_pages))

library = list_library()
book_idx = 0
if current_book in library:
    book_idx = library.index(current_book)

mode = MODE_SETTINGS
settings_idx = 0
device_config_idx = 0
device_editing_idx = None

# saved_steps = load_saved_steps()
# last_sensor_steps = lsm6ds3_steps()

saved_steps, today_steps, step_day = load_step_state()
last_sensor_steps = lsm6ds3_steps()

print("\nStarting in settings menu...")
profile_memory("before render_settings")
render_settings(settings_idx, full=True)
print("\nReady. Select READ, WALK, LIBRARY, or DEVICE.")

# ── Main loop ─────────────────────────────────────────────────────────────────
while True:
    next_action = next_btn.read()
    prev_action = prev_btn.read()
    settings_action = settings_btn.read()

    # ── SETTINGS button ───────────────────────────────────────────────────────
    if settings_action == "long":
        if mode == MODE_DEVICE:
            mode = MODE_SETTINGS
            settings_idx = 3
            render_settings(settings_idx, full=True)
        elif mode == MODE_LIBRARY:
            mode = MODE_SETTINGS
            settings_idx = 2
            render_settings(settings_idx, full=True)
        else:
            mode = MODE_SETTINGS
            settings_idx = 0
            render_settings(settings_idx, full=True)

    elif settings_action == "short":
        if mode == MODE_SETTINGS:
            chosen = SETTINGS_OPTIONS[settings_idx]

            if chosen == "READ":
                epd.init()
                mode = MODE_READ
                render_page_hybrid(page_lines, current_page, total_pages, force_full=True)

            elif chosen == "WALK":
                mode = MODE_WALK
                _walk_frame = 0
                steps = update_total_steps()
                render_walk_page_full(steps)

            elif chosen == "LIBRARY":
                mode = MODE_LIBRARY
                library = list_library()
                book_idx = 0
                if current_book in library:
                    book_idx = library.index(current_book)
                render_library(book_idx, full=True)

            elif chosen == "DEVICE":
                mode = MODE_DEVICE
                device_config_idx = 0
                device_editing_idx = None
                begin_config_edit()
                render_device_config(device_config_idx, device_editing_idx, full=True)
            
            elif chosen == "UPLOAD":
                fb = SCREEN_FB
                fb.fill(0xFF)

                fb.text("-- UPLOAD --", PADDING, PADDING, 0x00)
                fb.hline(PADDING, PADDING + CHAR_H + 4, SCREEN_W - PADDING * 2, 0x00)

                msg = "Rebooting to upload..."
                x = (SCREEN_W - len(msg) * 8) // 2
                y = SCREEN_H // 2

                fb.text(msg, x, y, 0x00)
                epd.display_frame_no_prev(SCREEN_BUF)

                sleep_ms(800)

                rtc = machine.RTC()
                rtc.memory(UPLOAD_BOOT_FLAG)

                machine.reset()
        elif mode == MODE_LIBRARY:
            library = list_library()
            if library:
                current_book = library[book_idx]
                save_current_book_index(current_book)
                current_book_path = BOOK_DIR + "/" + current_book

                current_offset = load_book_offset(current_book)
                page_lines, current_offset, next_offset, book_size = load_current_page(current_book_path, current_offset)
                print("Counting pages for selected book...")
                total_pages = count_total_pages(current_book_path)
                current_page = page_num_from_offset(current_book_path, current_offset)
                if current_page >= total_pages:
                    current_page = max(0, total_pages - 1)

                mode = MODE_READ
                render_page_hybrid(page_lines, current_page, total_pages, force_full=True)

        elif mode == MODE_DEVICE:
            num_editable = len(DEVICE_CONFIG_OPTIONS)

            if device_editing_idx is not None:
                key, _ = DEVICE_CONFIG_OPTIONS[device_editing_idx]

                if key == "pet_nickname":
                    device_name_char_idx += 1

                    if device_name_char_idx >= PET_NAME_MAX_LEN:
                        device_name_char_idx = 0
                        device_editing_idx = None
                if key == "current_date":
                    date_char_idx += 1

                    if date_char_idx == 4:
                        date_char_idx = 5
                    elif date_char_idx == 7:
                        date_char_idx = 8

                    if date_char_idx > 9:
                        date_char_idx = 0
                        device_editing_idx = None

                elif key == "current_time":
                    time_char_idx += 1

                    if time_char_idx == 2:
                        time_char_idx = 3

                    if time_char_idx > 4:
                        time_char_idx = 0
                        device_editing_idx = None
                else:
                    device_editing_idx = None

                render_device_config(device_config_idx, device_editing_idx, full=False)

            elif device_config_idx < num_editable:
                device_editing_idx = device_config_idx

                key, _ = DEVICE_CONFIG_OPTIONS[device_editing_idx]
                if key == "pet_nickname":
                    device_name_char_idx = 0
                elif key == "current_date":
                    date_char_idx = 0
                elif key == "current_time":
                    time_char_idx = 0

                render_device_config(device_config_idx, device_editing_idx, full=False)

            elif device_config_idx == num_editable:
                commit_config_edit()
                CHAR_W, CHAR_H = get_char_dimensions()
                recalculate_pagination()

                # Font/layout changed, so redraw from the same byte offset.
                # Byte offsets survive font-size changes better than page numbers.
                page_lines, current_offset, next_offset, book_size = load_current_page(current_book_path, current_offset)
                print("Recounting pages for new font/layout...")
                total_pages = count_total_pages(current_book_path)
                current_page = page_num_from_offset(current_book_path, current_offset)
                if current_page >= total_pages:
                    current_page = max(0, total_pages - 1)

                mode = MODE_SETTINGS
                settings_idx = 3
                render_settings(settings_idx, full=True)

            elif device_config_idx == num_editable + 1:
                discard_config_edit()
                mode = MODE_SETTINGS
                settings_idx = 3
                render_settings(settings_idx, full=True)

    # ── NEXT button ───────────────────────────────────────────────────────────
    if next_action == "long":
        if mode != MODE_DEVICE:
            enter_low_power_mode()

    elif next_action == "short":
        if mode == MODE_READ:
            if next_offset != current_offset:
                current_offset = next_offset
                current_page = min(current_page + 1, total_pages - 1)
                page_lines, current_offset, next_offset, book_size = load_current_page(current_book_path, current_offset)
                save_book_offset(current_book, current_offset)
                render_page_hybrid(page_lines, current_page, total_pages)

        elif mode == MODE_WALK:
            steps = update_total_steps()
            render_walk_update_hybrid(steps)

        elif mode == MODE_SETTINGS:
            settings_idx = (settings_idx - 1) % len(SETTINGS_OPTIONS)
            render_settings(settings_idx, full=False)

        elif mode == MODE_LIBRARY:
            library = list_library()
            if library:
                book_idx = (book_idx - 1) % len(library)
                render_library(book_idx, full=False)

        elif mode == MODE_DEVICE:
            if device_editing_idx is not None:
                key, _ = DEVICE_CONFIG_OPTIONS[device_editing_idx]
                adjust_config_value(key, 1)
                render_device_config(device_config_idx, device_editing_idx, full=False)
            else:
                max_idx = len(DEVICE_CONFIG_OPTIONS) + len(DEVICE_CONFIG_ACTIONS) - 1
                device_config_idx = (device_config_idx - 1) % (max_idx + 1)
                render_device_config(device_config_idx, device_editing_idx, full=False)

    # ── PREV button ───────────────────────────────────────────────────────────
    if prev_action == "short":
        if mode == MODE_READ:
            if current_offset > 0:
                current_offset = find_previous_offset(current_book_path, current_offset)
                current_page = max(0, current_page - 1)
                page_lines, current_offset, next_offset, book_size = load_current_page(current_book_path, current_offset)
                save_book_offset(current_book, current_offset)
                render_page_hybrid(page_lines, current_page, total_pages)

        elif mode == MODE_WALK:
            steps = update_total_steps()
            render_walk_update_hybrid(steps)

        elif mode == MODE_SETTINGS:
            settings_idx = (settings_idx + 1) % len(SETTINGS_OPTIONS)
            render_settings(settings_idx, full=False)

        elif mode == MODE_LIBRARY:
            library = list_library()
            if library:
                book_idx = (book_idx + 1) % len(library)
                render_library(book_idx, full=False)

        elif mode == MODE_DEVICE:
            if device_editing_idx is not None:
                key, _ = DEVICE_CONFIG_OPTIONS[device_editing_idx]
                adjust_config_value(key, -1)
                render_device_config(device_config_idx, device_editing_idx, full=False)
            else:
                max_idx = len(DEVICE_CONFIG_OPTIONS) + len(DEVICE_CONFIG_ACTIONS) - 1
                device_config_idx = (device_config_idx + 1) % (max_idx + 1)
                render_device_config(device_config_idx, device_editing_idx, full=False)

    sleep_ms(10)
