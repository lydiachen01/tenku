# main.py — Pride & Prejudice e-Paper Reader
# Waveshare 4.2" e-Paper V2 via ESP32 Driver Board
# Buttons on GPIO 34 (next page) and GPIO 35 (prev page)

from machine import Pin, SoftSPI
import framebuf
import time
from epaper4in2 import EPD

# ── Display config ────────────────────────────────────────────────────────────
SCREEN_W     = 400
SCREEN_H     = 300
PADDING      = 8
CHAR_W       = 10   # framebuf default font is 8x8 px
CHAR_H       = 10

# Usable area inside padding
TEXT_W = SCREEN_W - (PADDING * 2)  # 390 px
TEXT_H = SCREEN_H - (PADDING * 2)  # 290 px

COLS = TEXT_W // CHAR_W   # chars per line  → 48
ROWS = TEXT_H // CHAR_H   # lines per page  → 36

CHARS_PER_PAGE = COLS * ROWS  # 1728 chars max per page

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
# GPIO 32 & 33 have internal pull-ups — no external resistors needed
# Button pulls pin LOW when pressed
btn_next = Pin(32, Pin.IN, Pin.PULL_UP)
btn_prev = Pin(33, Pin.IN, Pin.PULL_UP)

# ── Text pagination ───────────────────────────────────────────────────────────
def build_pages(filepath):
    """
    Read a text file and split it into pages.
    Each page is a list of lines that fit within COLS x ROWS.
    Words are never split mid-word across lines.
    A word that does not fully fit on a line is carried to the next line (buffer).
    """
    print("Reading file:", filepath)
    with open(filepath, "r") as f:
        raw = f.read()

    # Normalise whitespace — collapse newlines/tabs into spaces
    raw = raw.replace("\r\n", " ").replace("\n", " ").replace("\t", " ")
    words = raw.split(" ")
    words = [w for w in words if w]  # drop empty strings

    pages = []
    current_lines = []
    current_line  = ""
    buffer_word   = None

    for word in words:
        # Start line with buffered word from previous line if present
        test_line = (buffer_word + " " + word) if buffer_word else word
        buffer_word = None

        # Does the word itself exceed one full line? Hard-wrap it.
        # (Rare in prose but handles very long hyphenated strings)
        if len(word) > COLS:
            word = word[:COLS]  # truncate — edge case only

        # Try appending word to the current line
        if current_line == "":
            tentative = word
        else:
            tentative = current_line + " " + word

        if len(tentative) <= COLS:
            # Word fits on current line
            current_line = tentative
        else:
            # Word does not fit — push current line, start new line with this word
            current_lines.append(current_line)
            current_line = word

            # Check if we've filled a page
            if len(current_lines) >= ROWS:
                pages.append(current_lines[:ROWS])
                current_lines = []

    # Flush the last line
    if current_line:
        current_lines.append(current_line)
    # Flush the last page
    if current_lines:
        pages.append(current_lines)

    print("Total pages:", len(pages))
    return pages


# ── Rendering ─────────────────────────────────────────────────────────────────
def render_page(page_lines, page_num, total_pages):
    """Draw a page of lines to the e-paper display."""
    buf = bytearray(SCREEN_W * SCREEN_H // 8)
    fb  = framebuf.FrameBuffer(buf, SCREEN_W, SCREEN_H, framebuf.MONO_HLSB)
    fb.fill(0xFF)  # white background

    for row_idx, line in enumerate(page_lines):
        print(line)
        x = PADDING
        y = PADDING + (row_idx * CHAR_H)
        fb.text(line, x, y, 0x00)

    # Page indicator bottom-right (small, inside padding would overlap — put at very bottom)
    indicator = "{}/{}".format(page_num + 1, total_pages)
    ind_x = SCREEN_W - PADDING - (len(indicator) * CHAR_W)
    ind_y = SCREEN_H - CHAR_H - 2
    fb.text(indicator, ind_x, ind_y, 0x00)

    epd.init()
    epd.display_frame(buf)
    epd.sleep()


# ── Button debounce ───────────────────────────────────────────────────────────
DEBOUNCE_MS = 200
last_press  = 0

def button_pressed(pin):
    """Return True if pin is LOW (button pressed) with debounce."""
    global last_press
    if pin.value() == 0:
        now = time.ticks_ms()
        if time.ticks_diff(now, last_press) > DEBOUNCE_MS:
            last_press = now
            return True
    return False


# ── Main ──────────────────────────────────────────────────────────────────────
print("Building pages...")
pages      = build_pages("/sample.txt")
total      = len(pages)
current    = 0

print("Rendering first page...")
render_page(pages[current], current, total)
print("Ready. Use buttons to turn pages.")

while True:
    if button_pressed(btn_next):
        if current < total - 1:
            current += 1
            print("Page", current + 1)
            render_page(pages[current], current, total)

    if button_pressed(btn_prev):
        if current > 0:
            current -= 1
            print("Page", current + 1)
            render_page(pages[current], current, total)

    time.sleep_ms(50)  # small sleep to avoid hammering the CPU