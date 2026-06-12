import network
import espnow
from machine import Pin, I2C, SPI
import ssd1306
import struct
from utime import sleep, sleep_us, ticks_us, ticks_diff
import _thread

# ==========================================
# CONFIG
# ==========================================
CHANNEL = 1
MAESTRO_MAC = b'\x80\xb5\x4e\xf8\x2d\x6c'
SAMPLE_RATE_HZ = 128
INTERVAL_US = int(1000000 / SAMPLE_RATE_HZ)

# ==========================================
# HARDWARE INIT
# ==========================================
i2c = I2C(0, scl=Pin(6), sda=Pin(5))
oled = ssd1306.SSD1306_I2C(128, 64, i2c)

# changing screen orientation 
oled.write_cmd(0xA0)
oled.write_cmd(0xC0)

cs = Pin(1, Pin.OUT, value=1)
spi = SPI(1, baudrate=2000000, polarity=0, phase=0, sck=Pin(7), mosi=Pin(9), miso=Pin(8))
led = Pin(21, Pin.OUT)

# ==========================================
# VARIABLES GLOBALES
# ==========================================
current_data = {"x": 0, "y": 0, "z": 0, "status": "IDLE"}
sensing_active = True

# ==========================================
# ESP-NOW
# ==========================================
wlan = network.WLAN(network.STA_IF)
wlan.active(True)

mac = wlan.config('mac')
mac_str = ':'.join('{:02X}'.format(b) for b in mac)

oled.fill(0)
oled.text('SENSOR MAC', 0, 0)
oled.text(mac_str[:15], 0, 16)
if len(mac_str) > 15:
    oled.text(mac_str[15:], 0, 28)
oled.show()
sleep(5)

en = espnow.ESPNow()
en.active(True)

try:
    en.add_peer(MAESTRO_MAC)
except:
    pass

CHANNEL = 1

for channel in range(1, 14):
    wlan.config(channel=channel)

    oled.fill(0)
    oled.text("Connecting...", 0, 0)
    oled.text("CH:" + str(channel), 0, 14)
    oled.show()

    sleep(0.3)

    try:
        en.send(MAESTRO_MAC, b"DISCOVER")
        host, msg = en.recv(1000)

        if msg == b"ACK":
            CHANNEL = channel

            oled.fill(0)
            oled.text("FOUND", 0, 0)
            oled.text("CH:" + str(CHANNEL), 0, 14)
            oled.show()
            sleep(1)
            break

    except:
        pass

wlan.config(channel=CHANNEL)

# ==========================================
# SENSOR FUNCS
# ==========================================
def write_reg(reg, value):
    cs.value(0)
    spi.write(bytearray([(reg << 1) | 0, value]))
    cs.value(1)

def read_accel():
    cs.value(0)
    spi.write(bytearray([(0x08 << 1) | 1]))
    data = spi.read(9)
    cs.value(1)
    def conv(b):
        val = ((b[0] << 12) | (b[1] << 4) | (b[2] >> 4))
        if val & 0x80000: val -= 0x100000
        return val
    return conv(data[0:3]), conv(data[3:6]), conv(data[6:9])

# ==========================================
# HILO DEL OLED
# ==========================================
def oled_thread():
    while True:
        oled.fill(0)
        oled.text("EPIC SENSOR", 0, 0)
        oled.text(f"Chanel: {CHANNEL}", 0, 14)
        oled.text("X:{:.3f}".format(current_data["x"]/256000), 0, 28)
        oled.text("Y:{:.3f}".format(current_data["y"]/256000), 0, 40)
        oled.text(current_data["status"], 0, 56)
        oled.show()
        sleep(0.2)

# ==========================================
# MAIN LOOP
# ==========================================
write_reg(0x2D, 0x00) # Wake up
_thread.start_new_thread(oled_thread, ())

next_sample = ticks_us()

while True:
    led.value(0) # LED ON
    now = ticks_us()
    if now >= next_sample:
        x, y, z = read_accel()
        current_data.update({"x": x, "y": y, "z": z})
        
        msg = struct.pack('iii', x, y, z)
        try:
            en.send(MAESTRO_MAC, msg, False)
            current_data["status"] = "TX OK"
        except:
            current_data["status"] = "TX ERR"
        
        next_sample += INTERVAL_US
        if ticks_diff(ticks_us(), next_sample) > INTERVAL_US:
            next_sample = ticks_us()
