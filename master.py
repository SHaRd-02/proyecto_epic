from machine import Pin, I2C, SDCard
import network
import espnow
import struct
import urequests
import ssd1306
import os
import gc
import _thread

from wifi_manager import WifiManager
from utime import sleep, ticks_ms, ticks_diff

# =========================================================
# CONFIG
# =========================================================
SUPABASE_URL = "https://paflyeftbszzjhkivmnh.supabase.co"
SUPABASE_TABLE = "sensor_data"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InBhZmx5ZWZ0YnN6empoa2l2bW5oIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc3MDQwNjE1MiwiZXhwIjoyMDg1OTgyMTUyfQ.mb3XrnkYT0W2UIVEBkZjwkeTIeeKn2pVJIYRV2KJv6o"

NODE_ID = "EPIC_NODE_01"
SENSOR_MAC = b'\xE0\x72\xA1\xFC\x45\xC8'

# =========================================================
# SWITCH CONFIG (GPIO 1 a GND)
# =========================================================
switch_upload = Pin(1, Pin.IN, Pin.PULL_UP)

# =========================================================
# OLED
# =========================================================
i2c = I2C(0, scl=Pin(41), sda=Pin(42))
oled = ssd1306.SSD1306_I2C(128, 64, i2c)
oled.write_cmd(0XA0)
oled.write_cmd(0XC0)

def screen(lines):
    oled.fill(0)
    for i, l in enumerate(lines):
        oled.text(str(l), 0, i * 10)
    oled.show()

# =========================================================
# VARIABLES GLOBALES
# =========================================================
wifi_ok = False
sd_ok = False
espnow_ok = False

wifi_ip = "0.0.0.0"
wifi_ch = 0

last_x, last_y, last_z = 0, 0, 0
packet_count = 0
saved_count = 0
upload_ok = 0
upload_fail = 0
rx_count = 0
sd_saved_count = 0
upload_count = 0
MAX_BUFFER = 500
recording_enabled = False

last_upload_status = "NONE"
last_batch_upload = ticks_ms()

# BUFFER EN RAM
data_buffer = []
buffer_lock = _thread.allocate_lock()

UPLOAD_BATCH_SIZE = 50
upload_request = False
state_lock = _thread.allocate_lock()

# =========================================================
# FUNCIONES DEL PUNTERO
# =========================================================
def cargar_estado():
    estado = {"rx":0, "sd":0, "upload":0}
    try:
        with open("/sd/estado.txt", "r") as f:
            for line in f:
                k,v = line.strip().split(":")
                estado[k] = int(v)
    except:
        pass
    return estado


def guardar_estado():
    try:
        with open("/sd/estado.txt", "w") as f:
            f.write("rx:" + str(rx_count) + "\n")
            f.write("sd:" + str(sd_saved_count) + "\n")
            f.write("upload:" + str(upload_count) + "\n")
    except Exception as e:
        print("STATE SAVE ERROR", e)

# =========================================================
# WIFI, SD & ESPNOW INIT
# =========================================================
WIFI_SSID = "ProyectoEpic"
WIFI_PASSWORD = "ProyectoEpic2026"
wm = WifiManager(ssid=WIFI_SSID, password=WIFI_PASSWORD, oled=oled)

def init_wifi():
    global wifi_ok, wifi_ip, wifi_ch
    try:
        wm.connect()
        t = 0
        while not wm.is_connected() and t < 15:
            screen(["WIFI CONNECT", "Retrying: " + str(t)])
            sleep(1)
            t += 1
        if wm.is_connected():
            wifi_ok = True
            wifi_ip = wm.wlan_sta.ifconfig()[0]
            wifi_ch = wm.wlan_sta.config("channel")
            print("WIFI OK | IP:", wifi_ip, "| CH:", wifi_ch)
        else:
            wifi_ok = False
            print("WIFI FAILED - Modo Offline")
    except Exception as e:
        wifi_ok = False
        print("WIFI ERROR:", e)

def init_sd():
    global sd_ok
    try:
        sd = SDCard(slot=0, width=1, cmd=Pin(38), sck=Pin(39), data=[Pin(40)])
        os.mount(sd, "/sd")
        if "data.csv" not in os.listdir("/sd"):
            with open("/sd/data.csv", "w") as f:
                f.write("t,x,y,z\n")
        sd_ok = True
        print("SD OK")
    except Exception as e:
        sd_ok = False
        print("SD ERROR:", e)

def init_state():
    global rx_count, sd_saved_count, upload_count
    estado = cargar_estado()
    rx_count = estado["rx"]
    sd_saved_count = estado["sd"]
    upload_count = estado["upload"]

def init_espnow():
    global en, espnow_ok
    try:
        en = espnow.ESPNow()
        en.active(True)
        en.add_peer(SENSOR_MAC)
        espnow_ok = True
        print("ESPNOW OK")
    except Exception as e:
        espnow_ok = False
        print("ESPNOW ERROR:", e)

# =========================================================
# BATCH UPLOAD CON PUNTERO
# =========================================================
def upload_batch():
    global upload_ok, upload_fail, last_upload_status, upload_count
    if not wifi_ok or not sd_ok: return

    r = None
    try:
        lines = []

        with open("/sd/data.csv", "r") as f:
            # Skip header
            header = f.readline()
            # Skip lines up to upload_count
            for _ in range(upload_count):
                if not f.readline():
                    break

            for _ in range(UPLOAD_BATCH_SIZE):
                line = f.readline()
                if not line:
                    break
                lines.append(line)

        if len(lines) == 0: 
            return

        payload = []
        for line in lines:
            try:
                t, x, y, z = line.strip().split(",")
                payload.append({
                    "node_id": NODE_ID,
                    "x_raw": int(x),
                    "y_raw": int(y),
                    "z_raw": int(z),
                    "sensor_timestamp_ms": int(t)
                })
            except: pass

        if len(payload) == 0: 
            return

        url = SUPABASE_URL + "/rest/v1/" + SUPABASE_TABLE
        headers = {
            "Content-Type": "application/json",
            "apikey": SUPABASE_KEY,
            "Authorization": "Bearer " + SUPABASE_KEY,
            "Prefer": "return=minimal"
        }

        r = urequests.post(url, json=payload, headers=headers, timeout=2)

        if r.status_code in [200, 201]:
            upload_count += len(payload)
            upload_ok += len(payload)
            last_upload_status = "OK"
            guardar_estado()
        else:
            upload_fail += len(payload)
            last_upload_status = f"F:{r.status_code}"

    except Exception as e:
        upload_fail += 1
        last_upload_status = "TIMEOUT"
        print("HTTP TIMEOUT/ERROR:", e)
    finally:
        if r is not None:
            try: r.close()
            except: pass
        gc.collect()

def upload_thread():
    global upload_request
    while True:
        if upload_request:
            upload_request = False
            try:
                upload_batch()
            except Exception as e:
                print("UPLOAD THREAD ERROR", e)
        sleep(1)

# =========================================================
# HILO SECUNDARIO (SD, OLED REORGANIZADO, CLOUD)
# =========================================================
def background_thread():
    global saved_count, last_batch_upload, upload_request, recording_enabled, temp_buffer, sd_saved_count
    while True:
        # 1. Refrescar Display Reorganizado
        str_w = "OK" if wifi_ok else "NO"
        str_sd = "OK" if sd_ok else "NO"
        str_e = "OK" if espnow_ok else "NO"
        
        oled.fill(0)
        # Estados y Canal
        oled.text(f"W:{str_w} S:{str_sd} E:{str_e}", 0, 0)
        oled.text(f"CH: {wifi_ch}", 0, 10)
        if recording_enabled:
            oled.text("REC", 100, 10)
        
        # Ejes X e Y
        oled.text(f"X:{last_x} Y:{last_y}", 0, 22)
        
        # Contadores con más espacio para no saturar el final
        oled.text(f"RX: {rx_count}", 0, 34)
        oled.text(f"SD: {sd_saved_count}", 0, 46)
        oled.text(f"UP: {upload_ok} {last_upload_status}", 0, 57)

        oled.show()

        # 2. Vaciar el Buffer de RAM hacia la SD
        if len(data_buffer) > 0:
            with buffer_lock:
                temp_buffer = list(data_buffer)
                data_buffer.clear()

            if sd_ok and recording_enabled:
                try:
                    with open("/sd/data.csv", "a") as f:
                        for sample in temp_buffer:
                            f.write("{},{},{},{}\n".format(sample[0], sample[1], sample[2], sample[3]))
                    saved_count += len(temp_buffer)
                    sd_saved_count += len(temp_buffer)
                    guardar_estado()
                except Exception as e:
                    print("SD WRITE ERROR:", e)

        # 3. Subida a Internet cada 5 segundos
        if ticks_diff(ticks_ms(), last_batch_upload) > 5000:
            last_batch_upload = ticks_ms()
            if switch_upload.value() == 0:
                upload_request = True

        sleep(0.05)

# =========================================================
# MAIN INITIALIZATION
# =========================================================
screen(["BOOTING..."])
sleep(1)
init_wifi()
init_sd()
init_state()
init_espnow()
screen(["READY"])
sleep(1)

_thread.start_new_thread(background_thread, ())
_thread.start_new_thread(upload_thread, ())

# =========================================================
# LOOP PRINCIPAL: CORE 0 RECEPTOR (128Hz)
# =========================================================
print("CORE 0 ESCUCHANDO ESP-NOW...")

while True:
    if en.any():
        try:
            host, msg = en.recv(10)
            if msg:
                if msg == b"DISCOVER":
                    answer = f"ACK:{wifi_ch}".encode()
                    en.send(host, answer)
                    continue

                x, y, z = struct.unpack("iii", msg)
                last_x, last_y, last_z = x, y, z
                packet_count += 1
                rx_count += 1
                if rx_count % 100 == 0:
                    guardar_estado()
                recording_enabled = (switch_upload.value() == 0)
                
                if recording_enabled:
                    with buffer_lock:
                        if len(data_buffer) < MAX_BUFFER:
                            data_buffer.append((ticks_ms(), x, y, z))

                if packet_count % 500 == 0:
                    print(f"Packets Recv: {packet_count} | Saved SD: {saved_count}")
        except OSError:
            pass
    sleep(0.001)
