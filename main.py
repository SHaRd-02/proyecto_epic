import network
import espnow
from machine import Pin, I2C, SPI
import ssd1306
import struct
from utime import sleep

# --- CONFIGURACIÓN ---
# OLED I2C
i2c = I2C(0, scl=Pin(6), sda=Pin(5))
oled = ssd1306.SSD1306_I2C(128, 64, i2c)

# ADXL355 SPI
cs = Pin(1, Pin.OUT, value=1)
spi = SPI(1, baudrate=2000000, polarity=0, phase=0, sck=Pin(7), mosi=Pin(9), miso=Pin(8))

# Botón y Comunicación
start_btn = Pin(2, Pin.IN, Pin.PULL_UP)
led = Pin(21, Pin.OUT)
wlan = network.WLAN(network.STA_IF)
wlan.active(True)
en = espnow.ESPNow()
en.active(True)

# !!! REEMPLAZA CON LA MAC DE TU FREENOVE !!!
MAESTRO_MAC = b'\x80\xb5\x4e\xf8\x2d\x6c' # Esta es la forma más segura en bytes
try:
    en.add_peer(MAESTRO_MAC)
except OSError:
    print("El par ya existe o hay un error")

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
        val = (b[0] << 12) | (b[1] << 4) | (b[2] >> 4)
        if val & 0x80000: val -= 0x100000
        return val # Mandamos el valor entero para no perder precisión
    return conv(data[0:3]), conv(data[3:6]), conv(data[6:9])

# Inicializar
write_reg(0x2D, 0x00)

while True:
    sensing_active = not start_btn.value() # Invertido por PULL_UP
    led.value( not sensing_active)
    oled.fill(0)
    
    if sensing_active:
        x, y, z = read_accel()
        # Enviar al Maestro (3 enteros de 32 bits)
        msg = struct.pack('iii', x, y, z)
        try:
            en.send(MAESTRO_MAC, msg)
            status = "TX OK"
        except:
            status = "TX ERR"
            
        oled.text("EPIC - SENSING", 10, 0)
        oled.text(f"X: {x/256000:.3f}g", 0, 20)
        oled.text(f"Y: {y/256000:.3f}g", 0, 35)
        oled.text(status, 80, 55) # Confirmación de envío
    else:
        oled.text("PROYECTO EPIC", 15, 10)
        oled.text("MODO: STANDBY", 10, 35)
        oled.text("> PULSE START <", 5, 55)
    
    oled.show()
    sleep(0.1)