from machine import Pin, I2C, SDCard
import network
import espnow
import struct
import urequests
import ssd1306
import os
import gc

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

# change oled orientation

oled.write_cmd(0XA0)
oled.write_cmd(0XC0)

def screen(lines):
    oled.fill(0)
    for i, l in enumerate(lines):
        oled.text(str(l), 0, i * 10)
    oled.show()

# =========================================================
# GLOBAL
# =========================================================

wifi_ok = False
sd_ok = False
espnow_ok = False

wifi_ip = "0.0.0.0"
wifi_ch = 0

last_x = 0
last_y = 0
last_z = 0

packet_count = 0
saved_count = 0

upload_ok = 0
upload_fail = 0

last_upload_status = "NONE"

last_error = ""

last_batch_upload = ticks_ms()

# =========================================================
# WIFI
# =========================================================

WIFI_SSID = "ProyectoEpic"
WIFI_PASSWORD = "ProyectoEpic2026"

wm = WifiManager(
    ssid=WIFI_SSID,
    password=WIFI_PASSWORD,
    oled=oled
)

# =========================================================
# WIFI INIT
# =========================================================

def init_wifi():
    global wifi_ok
    global wifi_ip
    global wifi_ch

    try:
        wm.connect()
        t = 0
        while not wm.is_connected() and t < 20:
            screen([
                "WIFI CONNECT",
                "Retrying: " + str(t)
            ])
            sleep(1)
            t += 1

        if wm.is_connected():
            wifi_ok = True
            wifi_ip = wm.wlan_sta.ifconfig()[0]
            wifi_ch = wm.wlan_sta.config("channel")
            print("WIFI OK")
            print("IP:", wifi_ip)
            print("CH:", wifi_ch)
        else:
            wifi_ok = False
            print("WIFI FAILED")
    except Exception as e:
        wifi_ok = False
        print("WIFI ERROR:", e)

# =========================================================
# SD INIT
# =========================================================

def init_sd():
    global sd_ok

    try:
        sd = SDCard(
            slot=0,
            width=1,
            cmd=Pin(38),
            sck=Pin(39),
            data=[Pin(40)]
        )
        os.mount(sd, "/sd")

        if "data.csv" not in os.listdir("/sd"):
            with open("/sd/data.csv", "w") as f:
                f.write("t,x,y,z\n")

        sd_ok = True
        print("SD OK")
    except Exception as e:
        sd_ok = False
        print("SD ERROR:", e)

# =========================================================
# ESPNOW INIT
# =========================================================

def init_espnow():
    global en
    global espnow_ok

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
# SAVE SD
# =========================================================

def save_sd(x, y, z):
    global saved_count

    if not sd_ok:
        return

    try:
        with open("/sd/data.csv", "a") as f:
            f.write("{},{},{},{}\n".format(
                ticks_ms(),
                x,
                y,
                z
            ))
        saved_count += 1
    except Exception as e:
        print("SD WRITE ERROR:", e)

# =========================================================
# BATCH UPLOAD (Opción 1 implementada)
# =========================================================

def upload_batch():
    global upload_ok
    global upload_fail
    global last_upload_status

    if not wifi_ok or not sd_ok:
        return

    try:
        lines = []
        with open("/sd/data.csv", "r") as f:
            header = f.readline()
            for i in range(50):
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
                    "sensor_timestamp_ms": int(t)  # <--- Enviamos el tick en milisegundos aquí
                })
            except:
                pass

        if len(payload) == 0:
            return

        url = SUPABASE_URL + "/rest/v1/" + SUPABASE_TABLE
        headers = {
            "Content-Type": "application/json",
            "apikey": SUPABASE_KEY,
            "Authorization": "Bearer " + SUPABASE_KEY,
            "Prefer": "return=minimal"
        }

        print("========== BATCH UPLOAD ==========")
        print("SAMPLES:", len(payload))

        r = urequests.post(
            url,
            json=payload,
            headers=headers
        )

        print("STATUS:", r.status_code)
        response = r.text
        print("RESPONSE:", response)

        if r.status_code == 201 or r.status_code == 200:
            upload_ok += len(payload)
            last_upload_status = "OK"
            print("UPLOAD SUCCESS")

            # REMOVE UPLOADED LINES
            with open("/sd/data.csv", "r") as f:
                all_lines = f.readlines()

            remaining = [all_lines[0]]
            remaining.extend(all_lines[len(lines)+1:])

            with open("/sd/data.csv", "w") as f:
                for l in remaining:
                    f.write(l)
        else:
            upload_fail += len(payload)
            last_upload_status = "FAIL"
            print("UPLOAD FAIL")

        r.close()
        gc.collect()

    except Exception as e:
        upload_fail += 1
        last_upload_status = "ERROR"
        print("UPLOAD EXCEPTION:", e)

# =========================================================
# DISPLAY
# =========================================================

def draw_main():
    oled.fill(0)
    oled.text("EPIC CENTRAL", 0, 0)
    oled.text("W:" + ("OK" if wifi_ok else "NO"), 0, 12)
    oled.text("SD:" + ("OK" if sd_ok else "NO"), 50, 12)
    oled.text("E:" + ("OK" if espnow_ok else "NO"), 0, 22)
    oled.text("CH:" + str(wifi_ch), 80, 22)
    oled.text("X:" + str(last_x), 0, 34)
    oled.text("Y:" + str(last_y), 0, 44)
    oled.text("Z:" + str(last_z), 0, 54)
    oled.text("UP:" + last_upload_status, 64, 44)
    oled.text(str(upload_ok), 64, 54)
    
    # Indicador discreto (Flecha) si el switch está mandando GND (activado)
    if switch_upload.value() == 0:
        oled.text("->", 112, 0)
        
    oled.show()

# =========================================================
# BOOT
# =========================================================

screen(["BOOTING..."])
sleep(2)

# =========================================================
# INIT
# =========================================================

screen(["INIT WIFI"])
init_wifi()
sleep(1)

screen(["INIT SD"])
init_sd()
sleep(1)

screen(["INIT ESPNOW"])
init_espnow()
sleep(1)

screen(["READY"])
sleep(1)

# =========================================================
# MAIN LOOP
# =========================================================

while True:
    try:
        draw_main()
        host, msg = en.recv(0)

        if msg:

            if msg == b"DISCOVER":
                en.send(host, b"ACK")
                continue

            x, y, z = struct.unpack("iii", msg)
            last_x = x
            last_y = y
            last_z = z

            packet_count += 1
            
            # IF de control para guardar datos en la SD
            if switch_upload.value() == 0:
                save_sd(x, y, z)

            if packet_count % 100 == 0:
                print("====================")
                print("PACKETS:", packet_count)
                print("SAVED:", saved_count)

        # UPLOAD EVERY 5 SECONDS
        if ticks_diff(ticks_ms(), last_batch_upload) > 5000:
            last_batch_upload = ticks_ms()
            
            # IF de control para subir datos a Supabase
            if switch_upload.value() == 0:
                upload_batch()

    except Exception as e:
        last_error = str(e)
        print("MAIN LOOP ERROR:", e)
        screen([
            "LOOP ERROR",
            str(e)[:20]
        ])

    sleep(0.0078)
