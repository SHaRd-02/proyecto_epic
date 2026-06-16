import network
import espnow
from machine import Pin, I2C, SPI, WDT ,ADC, reset_cause
import ssd1306
import struct
from utime import sleep, sleep_us, ticks_us, ticks_diff
import _thread
import gc

# ==========================================
# CONFIG
# ==========================================
CHANNEL = None
MAESTRO_MAC = b'\x80\xb5\x4e\xf8\x2d\x6c'
SAMPLE_RATE_HZ = 128
INTERVAL_US = int(1000000 / SAMPLE_RATE_HZ)

# ==========================================
# HARDWARE INIT
# ==========================================
battery_pin = ADC(Pin(2))
battery_pin.atten(ADC.ATTN_11DB)  # permite medir hasta ~3.3V
battery_samples = []

i2c = I2C(0, scl=Pin(6), sda=Pin(5))
oled = ssd1306.SSD1306_I2C(128, 64, i2c)

oled.write_cmd(0xA0)
oled.write_cmd(0xC0)

# Diagnóstico de motivo de reinicio al arrancar
causa_reset = reset_cause()
oled.fill(0)
oled.text("LAST RESET CAUSE:", 0, 0)
# 1=POWERON, 2=HARDWARE, 3=WATCHDOG, 4=SOFTWARE
oled.text(f"CODE: {causa_reset}", 0, 16)
oled.show()
sleep(3) # Dejar el motivo en pantalla 3 segundos para verlo

cs = Pin(1, Pin.OUT, value=1)
spi = SPI(1, baudrate=2000000, polarity=0, phase=0, sck=Pin(7), mosi=Pin(9), miso=Pin(8))
led = Pin(21, Pin.OUT)

# ==========================================
# VARIABLES GLOBALES & MONITOREO
# ==========================================
str_x = "0.000"
str_y = "0.000"
str_status = "BOOT"

# Contadores de diagnóstico y control
tx_ok = 0
tx_err = 0
consecutive_tx_errors = 0
oled_heartbeat = 0
last_oled_heartbeat = 0

# ==========================================
# ESP-NOW FUNCS
# ==========================================

def read_battery() -> tuple:
    global battery_samples

    raw = battery_pin.read_u16()
    voltage = (raw * 3.4 / 65535) * 2

    # Guardar muestra
    battery_samples.append(voltage)

    # Mantener últimas 20 lecturas
    if len(battery_samples) > 50:
        battery_samples.pop(0)

    # Promedio
    voltage = sum(battery_samples) / len(battery_samples)

    max_voltage = 4.20
    min_voltage = 3.00

    percent = ((voltage - min_voltage) / (max_voltage - min_voltage)) * 100

    percent = max(0, min(100, percent))

    return voltage, percent

def read_saved_channel() -> int:
    try:
        with open("channel.txt", "r") as f:
            return int(f.read().strip())
    except:
        return 1

def save_channel(channel: int) -> None:
    try:
        with open("channel.txt", "w") as f:
            f.write(str(channel))
    except:
        pass

def channel_connect(channel: int) -> bool:
    global CHANNEL
    wlan.config(channel=channel)
    oled.fill(0)
    oled.text("Connecting...", 0, 0)
    oled.text("CH:" + str(channel), 0, 14)
    oled.show()
    sleep(0.15)
    try:
        en.send(MAESTRO_MAC, b"DISCOVER")
        host, msg = en.recv(500)
        if msg and msg.split(b":")[0] == b"ACK":
            CHANNEL = int(msg.split(b":")[1])
            save_channel(CHANNEL)
            return True
    except:
        pass
    return False

wlan = network.WLAN(network.STA_IF)
wlan.active(True)
en = espnow.ESPNow()
en.active(True)

try: en.add_peer(MAESTRO_MAC)
except: pass

CHANNEL = read_saved_channel()
if not channel_connect(CHANNEL):
    for channel in range(1, 14):
        if channel_connect(channel=channel): break

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
# HILO DEL OLED (Reloj de segundos planos corregido)
# ==========================================
def oled_thread():
    global oled_heartbeat
    total_segundos = 0
    
    while True:
        try:
            oled_heartbeat += 1 
            
            # Cada 5 ciclos de 0.2s sumamos 1 segundo plano e inmune al desborde
            if oled_heartbeat % 5 == 0:
                total_segundos += 1
            
            # Cálculo matemático limpio del Uptime
            uptime_h = total_segundos // 3600
            uptime_m = (total_segundos % 3600) // 60
            
            # Calcular memoria libre actual
            mem_k = gc.mem_free() // 1024
            bat_v, bat_pct = read_battery()

            oled.fill(0)
            #oled.text(f"{bat_v:.2f} V", 0, 0)
            oled.text("EPIC Sensor", 0, 0)
            oled.text(f"{bat_pct:.0f}%", 100, 0)
            oled.text(f"CH:{CHANNEL} UP:{uptime_h}h{uptime_m}m", 0, 12)
            oled.text(f"X: {str_x}", 0, 24)
            oled.text(f"Y: {str_y}", 0, 34)
            oled.text(f"TX:{tx_ok} E:{tx_err}", 0, 44)
            oled.text(f"MEM:{mem_k}K {bat_v:.2f}V", 0, 54)
            oled.show()
        except:
            pass
        sleep(0.2)

# ==========================================
# MAIN LOOP (Core 0 enfocado en 128Hz)
# ==========================================
write_reg(0x2D, 0x00) # Wake up
_thread.start_new_thread(oled_thread, ())

last_gc = ticks_us()
last_heartbeat_check = ticks_us()

# ACTIVACIÓN DEL WATCHDOG (30 segundos de tolerancia al colapso)
wdt = WDT(timeout=30000) 

print("SENSOR COMPLETO Y CORRIENDO...")
last_time = ticks_us()

while True:
    now = ticks_us()
    
    # Planificador robusto usando ticks_diff >= 0
    if ticks_diff(now, last_time) >= 0:
        last_time = now + INTERVAL_US 
        
        # Leer Acelerómetro por SPI
        x, y, z = read_accel()
        str_x = "{:.3f}".format(x / 256000)
        str_y = "{:.3f}".format(y / 256000)
        
        # Envío por Radio ESP-NOW
        msg = struct.pack('iii', x, y, z)
        try:
            en.send(MAESTRO_MAC, msg, False)
            tx_ok += 1
            consecutive_tx_errors = 0
            str_status = "TX"
        except:
            tx_err += 1
            consecutive_tx_errors += 1
            str_status = "ERR"
            
        # Autorrecuperación de la antena si hay 100 errores seguidos
        if consecutive_tx_errors > 100:
            str_status = "RST_EN"
            try:
                en.active(False)
                sleep_us(500)
                en.active(True)
                en.add_peer(MAESTRO_MAC)
            except:
                pass
            consecutive_tx_errors = 0

        # Alimentar al Watchdog
        wdt.feed()

    # Forzar Garbage Collection cada 30 segundos
    if ticks_diff(ticks_us(), last_gc) > 30000000:
        gc.collect()
        last_gc = ticks_us()

    # Monitorear si el hilo del OLED se congela (Cada 5 segundos)
    if ticks_diff(ticks_us(), last_heartbeat_check) > 5000000:
        if oled_heartbeat == last_oled_heartbeat:
            str_status = "OLED_DEAD"
        last_oled_heartbeat = oled_heartbeat
        last_heartbeat_check = ticks_us()

    # Respiro del procesador
    sleep_us(50)