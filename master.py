from machine import Pin, I2C, SDCard
import network
import espnow
import struct
import urequests
import ssd1306
import os
from wifi_manager import WifiManager
from utime import sleep, ticks_ms

# =========================================================
# CONFIG
# =========================================================




SUPABASE_URL = "https://ezsomflzqxjmahohabqk.supabase.co"
SUPABASE_TABLE = "sensor_data"
SUPABASE_KEY = "TU_KEY"

NODE_ID = "EPIC_NODE_01"

SENSOR_MAC = b'\x34\x85\x18\xab\xcd\xef'

# =========================================================
# OLED
# =========================================================

i2c = I2C(0, scl=Pin(41), sda=Pin(42))
oled = ssd1306.SSD1306_I2C(128, 64, i2c)

def screen(lines):
    oled.fill(0)
    for i, l in enumerate(lines):
        oled.text(str(l), 0, i * 10)
    oled.show()

# =========================================================
# ESTADO GLOBAL
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
last_error = ""

# =========================================================
# ESTADOS
# =========================================================

BOOT = 0
WIFI = 1
SD = 2
ESPNOW = 3
RUN = 4

state = BOOT

# =========================================================
# WIFI INIT
# =========================================================

WIFI_SSID = "ProyectoEpic"
WIFI_PASSWORD = "ProyectoEpic2026"
wm = WifiManager(ssid = WIFI_SSID, password = WIFI_PASSWORD, oled = oled)

def init_wifi():
    global wifi_ok, wifi_ip, wifi_ch

    try:
        wm.connect()
        t = 0
        while not wm.is_connected() and t < 20:
            screen(["WIFI CONNECT", str(t)])
            sleep(1)
            t += 1

        if wm.is_connected():
            wifi_ok = True
            
            wifi_ip = wm.wlan_sta.ifconfig()[0]
            
            # get current channel
            wifi_ch = wm.wlan_sta.config("channel")
        else:
            wifi_ok = False

    except Exception as e:
        wifi_ok = False

# =========================================================
# SD INIT (TU CONFIG FUNCIONAL)
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

    except Exception as e:
        sd_ok = False

# =========================================================
# ESPNOW INIT
# =========================================================

def init_espnow():
    global en, espnow_ok

    try:
        en = espnow.ESPNow()
        en.active(True)
        en.add_peer(SENSOR_MAC)
        espnow_ok = True

    except:
        espnow_ok = False

# =========================================================
# SAVE SD
# =========================================================

def save_sd(x, y, z):
    if not sd_ok:
        return

    try:
        with open("/sd/data.csv", "a") as f:
            f.write("{},{},{},{}\n".format(
                ticks_ms(), x, y, z
            ))
    except:
        pass

# =========================================================
# SUPABASE
# =========================================================

def upload(x, y, z):
    if not wifi_ok:
        return

    try:
        url = SUPABASE_URL + "/rest/v1/" + SUPABASE_TABLE

        headers = {
            "Content-Type": "application/json",
            "apikey": SUPABASE_KEY,
            "Authorization": "Bearer " + SUPABASE_KEY
        }

        data = {
            "node_id": NODE_ID,
            "x_raw": int(x),
            "y_raw": int(y),
            "z_raw": int(z)
        }

        r = urequests.post(url, json=data, headers=headers)
        r.close()

    except:
        pass

# =========================================================
# DISPLAY PRINCIPAL
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

    oled.show()

# =========================================================
# BOOT
# =========================================================

screen(["BOOTING..."])
sleep(2)

# =========================================================
# INIT SEQUENCE
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

screen(["SYSTEM READY"])
sleep(2)

# =========================================================
# MAIN LOOP
# =========================================================

while True:

    try:
        draw_main()

        host, msg = en.recv(50)

        if msg:

            x, y, z = struct.unpack("iii", msg)

            last_x = x
            last_y = y
            last_z = z

            packet_count += 1

            save_sd(x, y, z)

            if packet_count % 5 == 0:
                upload(x, y, z)

    except Exception as e:
        last_error = str(e)
        screen(["LOOP ERROR", str(e)[:20]])

    sleep(0.05)
