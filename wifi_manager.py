# Author: Igor Ferreira
# License: MIT
# Version: 2.1.0
# Description: WiFi Manager for ESP8266 and ESP32 using MicroPython.

import machine
import network
import socket
import _thread
import re
import time
import ssd1306


class WifiManager:

    def __init__(self, ssid = 'WifiManager', password = 'wifimanager', reboot = True, debug = False, oled=None):
        self.wlan_sta = network.WLAN(network.STA_IF)
        self.wlan_sta.active(True)
        self.wlan_ap = network.WLAN(network.AP_IF)
        
        # Avoids simple mistakes with wifi ssid and password lengths, but doesn't check for forbidden or unsupported characters.
        if len(ssid) > 32:
            raise Exception('The SSID cannot be longer than 32 characters.')
        else:
            self.ap_ssid = ssid
        if len(password) < 8:
            raise Exception('The password cannot be less than 8 characters long.')
        else:
            self.ap_password = password
            
        # Set the access point authentication mode to WPA2-PSK.
        self.ap_authmode = 3
        
        # The file were the credentials will be stored.
        # There is no encryption, it's just a plain text archive. Be aware of this security problem!
        self.wifi_credentials = 'wifi.dat'
        
        # Prevents the device from automatically trying to connect to the last saved network without first going through the steps defined in the code.
        self.wlan_sta.disconnect()
        
        # Change to True if you want the device to reboot after configuration.
        # Useful if you're having problems with web server applications after WiFi configuration.
        self.reboot = reboot
        
        self.debug = debug
        self.oled = oled

    def log(self, *args):
        text = ' '.join(str(a) for a in args)
        print(text)
        if self.oled:
            self.screen([
                text[i:i+21]
                for i in range(0, len(text), 21)
            ][:6])


    def connect(self):
        if self.wlan_sta.isconnected():
            return
        profiles = self.read_credentials()
        for ssid, *_ in self.wlan_sta.scan():
            ssid = ssid.decode("utf-8")
            if ssid in profiles:
                password = profiles[ssid]
                if self.wifi_connect(ssid, password):
                    return
        self.log('Could not connect to any WiFi network. Starting the configuration portal...')
        self.web_server()
        
    
    def disconnect(self):
        if self.wlan_sta.isconnected():
            self.wlan_sta.disconnect()


    def is_connected(self):
        return self.wlan_sta.isconnected()


    def get_address(self):
        return self.wlan_sta.ifconfig()


    def write_credentials(self, profiles):
        lines = []
        for ssid, password in profiles.items():
            lines.append('{0};{1}\n'.format(ssid, password))
        with open(self.wifi_credentials, 'w') as file:
            file.write(''.join(lines))


    def read_credentials(self):
        lines = []
        try:
            with open(self.wifi_credentials) as file:
                lines = file.readlines()
        except Exception as error:
            if self.debug:
                print(error)
            pass
        profiles = {}
        for line in lines:
            ssid, password = line.strip().split(';')
            profiles[ssid] = password
        return profiles


    def wifi_connect(self, ssid, password):
        self.log('Trying to connect to:', ssid)
        self.wlan_sta.connect(ssid, password)
        for _ in range(100):
            if self.wlan_sta.isconnected():
                self.log('Connected!', self.wlan_sta.ifconfig())
                return True
            else:
                self.log('.')
                time.sleep_ms(100)
        self.log('Connection failed!')
        self.wlan_sta.disconnect()
        return False

    
    def dns_server(self):

        dns_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        dns_socket.bind(('0.0.0.0', 53))

        while True:
            try:
                data, addr = dns_socket.recvfrom(512)

                ip = self.wlan_ap.ifconfig()[0]
                ip_bytes = bytes(map(int, ip.split('.')))

                response = data[:2]
                response += b'\x81\x80'
                response += data[4:6]
                response += data[4:6]
                response += b'\x00\x00\x00\x00'
                response += data[12:]
                response += b'\xc0\x0c'
                response += b'\x00\x01'
                response += b'\x00\x01'
                response += b'\x00\x00\x00\x3c'
                response += b'\x00\x04'
                response += ip_bytes

                dns_socket.sendto(response, addr)

            except Exception as error:
                if self.debug:
                    print(error)

    def web_server(self):
        self.wlan_ap.active(True)
        self.wlan_ap.config(essid = self.ap_ssid, password = self.ap_password, authmode = self.ap_authmode)
        try:
            _thread.start_new_thread(self.dns_server, ())
            self.log('DNS server started')
        except Exception as error:
            if self.debug:
                print(error)
        server_socket = socket.socket()
        server_socket.close()
        server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server_socket.bind(('', 80))
        server_socket.listen(1)
        self.log('Connect to', self.ap_ssid, 'at', self.wlan_ap.ifconfig()[0])

        self.screen([
            "WIFI SETUP",
            self.ap_ssid,
            "",
            "OPEN:",
            self.wlan_ap.ifconfig()[0]
        ])


        while True:
            if self.wlan_sta.isconnected():
                self.wlan_ap.active(False)
                if self.reboot:
                    self.log('Rebooting in 5 seconds...')
                    time.sleep(5)
                    machine.reset()
            self.client, addr = server_socket.accept()
            try:
                self.client.settimeout(5.0)
                self.request = b''
                try:
                    while True:
                        if '\r\n\r\n' in self.request:
                            # Fix for Safari browser
                            self.request += self.client.recv(512)
                            break
                        self.request += self.client.recv(128)
                except Exception as error:
                    # It's normal to receive timeout errors in this stage, we can safely ignore them.
                    if self.debug:
                        print(error)
                    pass
                if self.request:
                    if self.debug:
                        print(self.url_decode(self.request))
                    url = re.search('(?:GET|POST) /(.*?)(?:\\?.*?)? HTTP', self.request).group(1).decode('utf-8').rstrip('/')
                    if (
                        url == '' or
                        'generate_204' in url or
                        'hotspot-detect' in url or
                        'connecttest' in url or
                        'ncsi.txt' in url or
                        'success.txt' in url
                    ):
                        self.handle_root()

                    elif url == 'configure':
                        self.handle_configure()
                    else:
                        self.handle_not_found()
            except Exception as error:
                if self.debug:
                    print(error)
                return
            finally:
                self.client.close()


    def send_header(self, status_code = 200):
        self.client.send("""HTTP/1.1 {0} OK\r\n""".format(status_code))
        self.client.send("""Content-Type: text/html\r\n""")
        self.client.send("""Connection: close\r\n""")


    def send_response(self, payload, status_code = 200):
        self.send_header(status_code)
        self.client.sendall("""
            <!DOCTYPE html>
            <html lang="en">
                <head>
                    <title>WiFi Manager</title>
                    <meta charset="UTF-8">
                    <meta name="viewport" content="width=device-width, initial-scale=1">
                    <link rel="icon" href="data:,">
                </head>
                <body>
                    {0}
                </body>
            </html>
        """.format(payload))
        self.client.close()


    def handle_root(self):

        self.send_header()

        self.client.sendall("""
<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Proyecto EPIC</title>

<style>
body{
    margin:0;
    padding:20px;
    background:#0f172a;
    color:white;
    font-family:Arial,sans-serif;
}

.card{
    background:#1e293b;
    max-width:420px;
    margin:auto;
    border-radius:20px;
    padding:20px;
    box-shadow:0 0 20px rgba(0,0,0,.4);
}

h1{
    text-align:center;
    color:#38bdf8;
}

.subtitle{
    text-align:center;
    color:#94a3b8;
    margin-bottom:20px;
}

.wifi{
    background:#334155;
    padding:12px;
    border-radius:12px;
    margin:8px 0;
}

input[type=password]{
    width:100%;
    box-sizing:border-box;
    padding:14px;
    border:none;
    border-radius:12px;
    margin-top:15px;
    background:#0f172a;
    color:white;
}

button{
    width:100%;
    padding:14px;
    border:none;
    border-radius:12px;
    background:#38bdf8;
    color:black;
    font-weight:bold;
    margin-top:15px;
    font-size:16px;
}

label{
    margin-left:8px;
}
</style>
</head>

<body>

<div class="card">
<h1>Proyecto EPIC</h1>
<div class="subtitle">WiFi Configuration Portal</div>
<form action="/configure" method="post">
""")

        for ssid, *_ in self.wlan_sta.scan():
            ssid = ssid.decode("utf-8")

            self.client.sendall("""
<div class="wifi">
<input type="radio" name="ssid" value="{0}" id="{0}">
<label for="{0}">{0}</label>
</div>
""".format(ssid))

        self.client.sendall("""
<input
type="password"
name="password"
placeholder="WiFi Password">

<button type="submit">
CONNECT
</button>

</form>
</div>
</body>
</html>
""")

        self.client.close()


    def handle_configure(self):
        match = re.search('ssid=([^&]*)&password=(.*)', self.url_decode(self.request))
        if match:
            ssid = match.group(1).decode('utf-8')
            password = match.group(2).decode('utf-8')
            if len(ssid) == 0:
                self.send_response("""
                    <p>SSID must be providaded!</p>
                    <p>Go back and try again!</p>
                """, 400)
            elif self.wifi_connect(ssid, password):
                self.send_response("""
                    <p>Successfully connected to</p>
                    <h1>{0}</h1>
                    <p>IP address: {1}</p>
                """.format(ssid, self.wlan_sta.ifconfig()[0]))
                profiles = self.read_credentials()
                profiles[ssid] = password
                self.write_credentials(profiles)
                time.sleep(5)
            else:
                self.send_response("""
                    <p>Could not connect to</p>
                    <h1>{0}</h1>
                    <p>Go back and try again!</p>
                """.format(ssid))
                time.sleep(5)
        else:
            self.send_response("""
                <p>Parameters not found!</p>
            """, 400)
            time.sleep(5)


    def handle_not_found(self):
        self.send_response("""
            <p>Page not found!</p>
        """, 404)


    def url_decode(self, url_string):

        # Source: https://forum.micropython.org/viewtopic.php?t=3076
        # unquote('abc%20def') -> b'abc def'
        # Note: strings are encoded as UTF-8. This is only an issue if it contains
        # unescaped non-ASCII characters, which URIs should not.

        if not url_string:
            return b''

        if isinstance(url_string, str):
            url_string = url_string.encode('utf-8')

        bits = url_string.split(b'%')

        if len(bits) == 1:
            return url_string

        res = [bits[0]]
        appnd = res.append
        hextobyte_cache = {}

        for item in bits[1:]:
            try:
                code = item[:2]
                char = hextobyte_cache.get(code)
                if char is None:
                    char = hextobyte_cache[code] = bytes([int(code, 16)])
                appnd(char)
                appnd(item[2:])
            except Exception as error:
                if self.debug:
                    print(error)
                appnd(b'%')
                appnd(item)

        return b''.join(res)
    
    def screen(self, lines):

        if not self.oled:
            return

        self.oled.fill(0)

        for i, line in enumerate(lines):
            self.oled.text(str(line), 0, i * 10)

        self.oled.show()