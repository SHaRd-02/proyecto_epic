import network
import socket
import ujson
import time
import gc


CONFIG_FILE = "config.json"


# =========================================================
# UTIL: LOAD / SAVE CONFIG
# =========================================================
def load_config():
    try:
        with open(CONFIG_FILE, "r") as f:
            return ujson.load(f)
    except:
        return {}


def save_config(cfg):
    with open(CONFIG_FILE, "w") as f:
        ujson.dump(cfg, f)


# =========================================================
# WIFI MANAGER CLASS
# =========================================================
class WiFiManager:

    def __init__(self, ap_name="EPIC_SETUP"):

        self.ap_name = ap_name
        self.wlan_sta = network.WLAN(network.STA_IF)
        self.wlan_ap = network.WLAN(network.AP_IF)

        self.config = load_config()


    # -----------------------------------------------------
    # CONNECT NORMAL MODE
    # -----------------------------------------------------
    def connect(self, timeout=15):

        if "ssid" not in self.config:
            return False

        ssid = self.config["ssid"]
        password = self.config.get("password", "")

        self.wlan_sta.active(True)
        self.wlan_sta.connect(ssid, password)

        t = 0
        while not self.wlan_sta.isconnected() and t < timeout:
            time.sleep(1)
            t += 1

        return self.wlan_sta.isconnected()


    # -----------------------------------------------------
    # START ACCESS POINT
    # -----------------------------------------------------
    def start_ap(self):

        self.wlan_ap.active(True)
        self.wlan_ap.config(essid=self.ap_name)

        ip = self.wlan_ap.ifconfig()[0]
        return ip


    # -----------------------------------------------------
    # SCAN NETWORKS
    # -----------------------------------------------------
    def scan(self):

        self.wlan_sta.active(True)

        nets = self.wlan_sta.scan()

        result = []

        for n in nets:
            ssid = n[0].decode()
            rssi = n[3]

            if ssid:
                result.append((ssid, rssi))

        return result


    # -----------------------------------------------------
    # SIMPLE WEB PAGE
    # -----------------------------------------------------
    def _html(self, networks):

        options = ""

        for ssid, rssi in networks:
            options += '<option value="{}">{} ({})</option>'.format(
                ssid, ssid, rssi
            )

        html = """
        <html>
        <head>
        <title>EPIC WIFI</title>
        </head>

        <body style="font-family:Arial">

        <h2>EPIC WIFI CONFIG</h2>

        <form action="/save">

        <label>WiFi:</label><br>
        <select name="ssid">
        {options}
        </select>
        <br><br>

        <label>Password:</label><br>
        <input name="password" type="password"/>
        <br><br>

        <button type="submit">SAVE</button>

        </form>

        </body>
        </html>
        """.format(options=options)

        return html


    # -----------------------------------------------------
    # START WEB SERVER
    # -----------------------------------------------------
    def start_config_portal(self):

        ip = self.start_ap()
        nets = self.scan()

        addr = socket.socket()
        addr.bind(("0.0.0.0", 80))
        addr.listen(1)

        print("CONFIG PORTAL:", ip)

        while True:

            cl, addr = addr.accept()
            request = cl.recv(1024).decode()

            if "/save?" in request:

                try:
                    query = request.split("/save?")[1].split(" ")[0]

                    params = {}

                    for p in query.split("&"):
                        k, v = p.split("=")
                        params[k] = v.replace("+", " ")

                    self.config["ssid"] = params.get("ssid", "")
                    self.config["password"] = params.get("password", "")

                    save_config(self.config)

                    response = "WiFi Saved. Reboot device."

                except:
                    response = "Error saving config"

                cl.send("HTTP/1.1 200 OK\r\n\r\n" + response)
                cl.close()

                time.sleep(2)
                import machine
                machine.reset()

            else:

                html = self._html(nets)
                cl.send("HTTP/1.1 200 OK\r\nContent-Type: text/html\r\n\r\n")
                cl.send(html)
                cl.close()


    # -----------------------------------------------------
    # AUTO CONNECT OR FALLBACK
    # -----------------------------------------------------
    def auto_connect(self):

        if self.connect():
            return True

        # fallback to AP mode
        self.start_config_portal()
        return False