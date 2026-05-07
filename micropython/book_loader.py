import gc
import time
import network
import socket
import os

try:
    import urequests as requests
except ImportError:
    import requests

WIFI_SSID = "Tufts_Wireless"
LIBRARY_DIR = "/library"

def connect_wifi():
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    if not wlan.isconnected():
        print("[WIFI] Connecting to {}...".format(WIFI_SSID))
        wlan.connect(WIFI_SSID)
        start = time.time()
        while not wlan.isconnected() and (time.time() - start < 15):
            time.sleep(0.5)
    
    if wlan.isconnected():
        print("[WIFI] Connected! IP:", wlan.ifconfig()[0])
        return wlan.ifconfig()[0]
    return None

def download_to_file(url, custom_title, byte_limit):
    gc.collect()
    safe_title = custom_title.replace('+', '_').replace('%20', '_')[:100]
    filepath = "{}/{}.txt".format(LIBRARY_DIR, safe_title)
    
    print("\n[LOG] Requesting URL: {}".format(url))
    print("[LOG] Target File: {}".format(filepath))
    print("[LOG] Max Bytes: {}".format(byte_limit))

    try:
        # We use stream=True to avoid loading the whole response into RAM
        res = requests.get(url, stream=True)
        
        print("[LOG] Response Code: {}".format(res.status_code))
        
        if res.status_code != 200:
            msg = "Failed: Server returned {}".format(res.status_code)
            print("[LOG] " + msg)
            res.close()
            return msg

        bytes_written = 0
        with open(filepath, 'w') as f:
            print("[LOG] Writing to flash...")
            
            while bytes_written < byte_limit:
                # Read a small chunk from the raw stream
                remaining = byte_limit - bytes_written
                chunk_size = min(128, remaining)
                
                # .raw.read() is the MicroPython equivalent to iter_content
                chunk = res.raw.read(chunk_size)
                
                if not chunk:
                    print("[LOG] End of stream reached.")
                    break
                
                f.write(chunk)
                bytes_written += len(chunk)
                
                # Optional: Print progress every 1KB
                if bytes_written % 1024 == 0:
                    print("[LOG] Progress: {} bytes".format(bytes_written))

        res.close()
        gc.collect()
        success_msg = "Successfully saved {} bytes.".format(bytes_written)
        print("[LOG] " + success_msg)
        return success_msg

    except Exception as e:
        err = "Download error: {}".format(str(e))
        print("[LOG] " + err)
        return err

def get_html(status=""):
    return """<!DOCTYPE html>
    <html>
    <head>
        <title>ESP32 Book Loader</title>
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <style>
            body { font-family: sans-serif; margin: 20px; background: #f4f4f9; }
            .box { border: 1px solid #ccc; padding: 20px; border-radius: 12px; max-width: 450px; background: white; box-shadow: 0 2px 5px rgba(0,0,0,0.1); }
            input, select { width: 100%; padding: 10px; margin: 10px 0; display: block; border: 1px solid #ddd; border-radius: 6px; box-sizing: border-box; }
            button { background: #3498db; color: white; padding: 12px; border: none; width: 100%; cursor: pointer; border-radius: 6px; font-weight: bold; }
            .status { background: #e8f4fd; padding: 12px; margin-top: 15px; font-size: 0.9em; border-left: 4px solid #3498db; color: #2c3e50; }
        </style>
    </head>
    <body>
        <div class="box">
            <h2>Tenku+OpenLibrary Book Loader</h2>
            <form action="/get" method="get">
                <label>File Title (Max 100 chars):</label>
                <input type="text" name="t" maxlength="100" placeholder="e.g. Hobbit_Chapter1" required>
                
                <label>Byte Limit:</label>
                <input type="number" name="l" value="1000" min="1" max="100000">
                
                <label>Select Book Source:</label>
                <select name="u">
                    <option value="https://www.gutenberg.org/cache/epub/1342/pg1342.txt">Pride and Prejudice</option>
                    <option value="https://www.gutenberg.org/files/11/11-0.txt">Alice in Wonderland</option>
                    <option value="https://www.gutenberg.org/cache/epub/2701/pg2701.txt">Moby Dick</option>
                </select>
                <button type="submit">Download to /library</button>
            </form>
            """ + (f'<div class="status">{status}</div>' if status else "") + """
        </div>
    </body>
    </html>"""

def run_server():
    ip = connect_wifi()
    if not ip:
        print("[ERROR] WiFi Connection Failed.")
        return

    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(('', 80))
    s.listen(1)
    print("\n[SERVER] Online at http://{}".format(ip))

    while True:
        try:
            conn, addr = s.accept()
            # Increase buffer for slightly longer URLs
            request = conn.recv(1024).decode()
            
            response_msg = ""
            if "GET /get?" in request:
                print("[SERVER] New Download Request Received")
                # Simple parsing for URL parameters
                try:
                    params = request.split(' ')[1].split('?')[1]
                    p_map = {p.split('=')[0]: p.split('=')[1] for p in params.split('&')}
                    
                    url = p_map.get('u', '').replace('%3A', ':').replace('%2F', '/')
                    title = p_map.get('t', 'book')
                    limit = int(p_map.get('l', 1000))
                    
                    response_msg = download_to_file(url, title, limit)
                except Exception as parse_err:
                    response_msg = "Form Parsing Error: {}".format(parse_err)

            conn.send('HTTP/1.1 200 OK\nContent-Type: text/html\nConnection: close\n\n')
            conn.sendall(get_html(response_msg))
            conn.close()
            gc.collect()
        except Exception as e:
            print("[SERVER] Loop Error: {}".format(e))

if __name__ == "__main__":
    run_server()
