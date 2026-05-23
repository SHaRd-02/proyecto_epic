import network
import espnow
from machine import Pin, I2C, SPI
import ssd1306
import struct
from utime import sleep

# ==========================================
# CONFIG
# ==========================================

# COPIA EL CANAL DEL CENTRAL
CHANNEL = 11

# COPIA LA MAC DEL CENTRAL
MAESTRO_MAC = b'\x80\xb5\x4e\xf8\x2d\x6c'

# ==========================================
# OLED
# ==========================================
i2c = I2C(0, scl=Pin(6), sda=Pin(5))

oled = ssd1306.SSD1306_I2C(128, 64, i2c)

# ==========================================
# ADXL355 SPI
# ==========================================
cs = Pin(1, Pin.OUT, value=1)

spi = SPI(
    1,
    baudrate=2000000,
    polarity=0,
    phase=0,
    sck=Pin(7),
    mosi=Pin(9),
    miso=Pin(8)
)

# ==========================================
# BUTTON + LED
# ==========================================
start_btn = Pin(2, Pin.IN, Pin.PULL_UP)

led = Pin(21, Pin.OUT)

# ==========================================
# WIFI + ESP-NOW
# ==========================================
wlan = network.WLAN(network.STA_IF)

wlan.active(True)

# MUY IMPORTANTE
wlan.config(channel=CHANNEL)

print("CANAL:", wlan.config('channel'))

en = espnow.ESPNow()

en.active(True)

try:
    en.add_peer(MAESTRO_MAC)

    print("PEER OK")

except Exception as e:
    print("PEER ERR:", e)

# ==========================================
# ADXL355 FUNCS
# ==========================================
def write_reg(reg, value):

    cs.value(0)

    spi.write(
        bytearray([
            (reg << 1) | 0,
            value
        ])
    )

    cs.value(1)

def read_accel():

    cs.value(0)

    spi.write(
        bytearray([
            (0x08 << 1) | 1
        ])
    )

    data = spi.read(9)

    cs.value(1)

    def conv(b):

        val = (
            (b[0] << 12) |
            (b[1] << 4) |
            (b[2] >> 4)
        )

        if val & 0x80000:
            val -= 0x100000

        return val

    return (
        conv(data[0:3]),
        conv(data[3:6]),
        conv(data[6:9])
    )

# ==========================================
# INIT SENSOR
# ==========================================
write_reg(0x2D, 0x00)

# ==========================================
# LOOP
# ==========================================
while True:

    sensing_active = not start_btn.value()

    led.value(not sensing_active)

    oled.fill(0)

    if sensing_active:

        x, y, z = read_accel()

        msg = struct.pack('iii', x, y, z)

        try:
            en.send(MAESTRO_MAC, msg)

            status = "TX OK"

            print("TX:", x, y, z)

        except Exception as e:

            status = "TX ERR"

            print("SEND ERR:", e)

        oled.text("EPIC SENSOR", 0, 0)

        oled.text("CH:" + str(CHANNEL), 0, 12)

        oled.text(
            "X:{:.2f}".format(x / 256000),
            0,
            28
        )

        oled.text(
            "Y:{:.2f}".format(y / 256000),
            0,
            40
        )

        oled.text(status, 0, 56)

    else:

        oled.text("EPIC", 40, 10)

        oled.text("STANDBY", 25, 30)

        oled.text("PRESS BUTTON", 5, 50)

    oled.show()

    sleep(0.1)