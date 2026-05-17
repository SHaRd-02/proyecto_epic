from machine import Pin, I2C, SPI
import os
import network
import espnow
import struct
from utime import ticks_ms, sleep

# ==========================================
# LIBRERÍA SDCard INTEGRADA
# ==========================================
class SDCard:
    def __init__(self, spi, cs):
        self.spi = spi
        self.cs = cs
        self.cmdbuf = bytearray(6)
        self.tokenbuf = bytearray(1)
        self.cs.init(self.cs.OUT, value=1)
        self.init_card()

    def init_card(self):
        # Velocidad muy baja para inicializar tarjetas viejas
        self.spi.init(baudrate=100000) 
        for i in range(16): self.spi.write(b'\xff')
        if self.cmd(0, 0, 0x95) != 1: raise OSError("No SD")
        if self.cmd(8, 0x1aa, 0x87) == 1:
            for i in range(4): self.spi.read(1)
            while self.cmd(55, 0, 0) != 1 or self.cmd(41, 0x40000000, 0) != 0: pass
        else:
            while self.cmd(55, 0, 0) != 1 or self.cmd(41, 0, 0) != 0: pass
        # Subir a 5MHz para escritura estable
        self.spi.init(baudrate=5000000)

    def cmd(self, cmd, arg, crc):
        self.cs(0)
        self.cmdbuf[0] = 0x40 | cmd
        struct.pack_into(">I", self.cmdbuf, 1, arg)
        self.cmdbuf[5] = crc
        self.spi.write(self.cmdbuf)
        for i in range(10):
            self.spi.readinto(self.tokenbuf)
            if not (self.tokenbuf[0] & 0x80): break
        self.cs(1)
        self.spi.write(b'\xff')
        return self.tokenbuf[0]

    def readblocks(self, block_num, buf):
        self.cs(0)
        for i in range(block_num, block_num + len(buf) // 512):
            if self.cmd(17, i, 0) != 0: raise OSError(5)
            while self.spi.read(1) != b'\xfe': pass
            self.spi.readinto(buf)
            self.spi.read(2)
        self.cs(1)
        self.spi.write(b'\xff')

    def writeblocks(self, block_num, buf):
        self.cs(0)
        for i in range(block_num, block_num + len(buf) // 512):
            if self.cmd(24, i, 0) != 0: raise OSError(5)
            self.spi.write(b'\xfe')
            self.spi.write(buf)
            self.spi.write(b'\xff\xff')
            if (self.spi.read(1)[0] & 0x1f) != 0x05: raise OSError(5)
            while self.spi.read(1) == b'\x00': pass
        self.cs(1)
        self.spi.write(b'\xff')

    def count(self): return 0

# ==========================================
# INICIO
# ==========================================
import ssd1306

# 1. OLED (Pines 42 SDA, 41 SCL)
i2c = I2C(0, sda=Pin(42), scl=Pin(41), freq=400000)
oled = ssd1306.SSD1306_I2C(128, 64, i2c)

# 2. SD (Freenove S3 suele usar CS=10 o CS=14)
sd_status = "SD Error"
# SPI 1: SCK=12, MOSI=11, MISO=13
spi = SPI(1, sck=Pin(12), mosi=Pin(11), miso=Pin(13))

for cs_pin in [10, 14, 21]: # Añadimos Pin 14 y 21 por si acaso
    try:
        print(f"Probando CS {cs_pin}...")
        sd = SDCard(spi, Pin(cs_pin))
        vfs = os.VfsFat(sd)
        os.mount(vfs, "/sd")
        sd_status = "SD OK"
        print(f"¡SD LISTA en CS {cs_pin}!")
        break
    except:
        continue

# 3. ESP-NOW
wlan = network.WLAN(network.STA_IF)
wlan.active(True)
en = espnow.ESPNow()
en.active(True)

def update_ui(status, x=0, y=0, z=0):
    oled.fill(0)
    oled.text("EPIC CENTRAL", 15, 0)
    oled.text(f"SD: {sd_status}", 0, 15)
    oled.text(f"MODO: {status}", 0, 32)
    if x or y or z:
        oled.text(f"X:{x/256000:.2f} Y:{y/256000:.2f}", 0, 48)
        oled.text(f"Z:{z/256000:.2f}", 0, 58)
    oled.show()

update_ui("ESPERANDO...")

# 4. BUCLE
while True:
    host, msg = en.recv(100)
    if msg:
        try:
            x, y, z = struct.unpack('iii', msg)
            update_ui("DATOS OK", x, y, z)
            if sd_status == "SD OK":
                with open("/sd/data.csv", "a") as f:
                    f.write(f"{ticks_ms()},{x},{y},{z}\n")
        except: pass
    else:
        sleep(0.01)
