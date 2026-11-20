import time
import gc
import network
import socket
from machine import Pin, UART
from umqtt.simple import MQTTClient
from Arducam import *

# ============================================================
# CONFIGURATION WIFI
# ============================================================
from secrets import SSID, PASSWORD   # voir secrets_example.py

# ============================================================
# CONFIGURATION GATEWAY (upload des images de la camera)
# ============================================================
GATEWAY_IP = "192.168.1.62"
GATEWAY_PORT = 5000

# ============================================================
# CONFIGURATION MQTT (broker Mosquitto local, sur la meme VM)
# ============================================================
MQTT_BROKER = "192.168.1.62"
MQTT_PORT = 1883
MQTT_CLIENT_ID = "esp32_node1"

TOPIC_STATUS = b"network/node1/status"
TOPIC_CAPTEURS = b"network/node1/telemetry/msp432"   # trame JSON complete relayee telle quelle

# ============================================================
# BROCHES
# ============================================================
LED_PIN = 2      # LED integree, temoin du streaming camera

# --- UART2 : liaison serie avec le MSP432 (capteurs) ---
UART_MSP432_ID = 2
UART_MSP432_BAUDRATE = 9600
UART_MSP432_TX = 17   # GPIO17 (TX2) -> RXD (fil blanc) du MSP432
UART_MSP432_RX = 16   # GPIO16 (RX2) <- TXD (fil jaune) du MSP432

CHUNK_SIZE = 1024
DELAI_ENTRE_FRAMES_MS = 5
INTERVALLE_GC = 30

led = Pin(LED_PIN, Pin.OUT)
led.value(0)

uart_msp432 = UART(UART_MSP432_ID, baudrate=UART_MSP432_BAUDRATE,
                    tx=UART_MSP432_TX, rx=UART_MSP432_RX)
_buffer_msp432 = b""   # accumulateur pour reconstituer les lignes JSON


def connecter_wifi():
    """Connexion WiFi avec cycle propre de l'interface (evite Wifi Internal State Error)."""
    ap = network.WLAN(network.AP_IF)
    ap.active(False)
    wlan = network.WLAN(network.STA_IF)
    wlan.active(False)
    time.sleep(1)
    wlan.active(True)
    time.sleep(1)
    if not wlan.isconnected():
        print("Connexion au reseau", SSID)
        wlan.connect(SSID, PASSWORD)
        while not wlan.isconnected():
            time.sleep(0.5)
            print(".", end="")
    print("\nWiFi connecte")
    print("Adresse IP:", wlan.ifconfig()[0])
    return wlan


# ------------------------------------------------------------------
# MQTT
# ------------------------------------------------------------------
def connecter_mqtt():
    client = MQTTClient(MQTT_CLIENT_ID, MQTT_BROKER, port=MQTT_PORT, keepalive=30)
    client.set_last_will(TOPIC_STATUS, b"offline", retain=True)
    client.connect()
    client.publish(TOPIC_STATUS, b"online", retain=True)
    print("MQTT connecte au broker", MQTT_BROKER)
    return client


# ------------------------------------------------------------------
# Lecture non-bloquante de l'UART venant du MSP432, publication MQTT
# ------------------------------------------------------------------
def lire_msp432_et_publier(client):
    """Lit les octets deja disponibles sur l'UART2 (sans jamais attendre),
    reconstitue les lignes terminees par '\\n' et publie chaque ligne JSON
    complete recue du MSP432 sur MQTT. Ne bloque jamais le streaming camera."""
    global _buffer_msp432

    if uart_msp432.any():
        _buffer_msp432 += uart_msp432.read()

        while b"\n" in _buffer_msp432:
            ligne, _, _buffer_msp432 = _buffer_msp432.partition(b"\n")
            ligne = ligne.strip(b"\r").strip()

            if ligne.startswith(b"{") and ligne.endswith(b"}"):
                try:
                    client.publish(TOPIC_CAPTEURS, ligne, retain=True)
                    print("MSP432 ->", ligne)
                except OSError as e:
                    print("Erreur publication MQTT (trame MSP432 ignoree):", e)
            else:
                # ligne non exploitable (bruit de demarrage, trame coupee...)
                print("Ligne MSP432 ignoree (pas du JSON) :", ligne)


# ------------------------------------------------------------------
# Camera : connexion + envoi (identique a la version streaming validee)
# ------------------------------------------------------------------
def ouvrir_connexion_gateway():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(3)
    s.connect((GATEWAY_IP, GATEWAY_PORT))
    return s


def _lire_reponse(s):
    data = b""
    while b"\r\n\r\n" not in data:
        chunk = s.recv(256)
        if not chunk:
            raise OSError("connexion fermee par le serveur")
        data += chunk
    entetes, _, reste = data.partition(b"\r\n\r\n")
    content_length = 0
    for ligne in entetes.split(b"\r\n"):
        if ligne.lower().startswith(b"content-length:"):
            content_length = int(ligne.split(b":")[1].strip())
            break
    corps_recu = len(reste)
    while corps_recu < content_length:
        chunk = s.recv(min(256, content_length - corps_recu))
        if not chunk:
            break
        corps_recu += len(chunk)


def envoyer_image(s, mycam, length):
    entete = (
        "POST /upload HTTP/1.1\r\n"
        "Host: {}\r\n"
        "Content-Type: image/jpeg\r\n"
        "Content-Length: {}\r\n"
        "Connection: keep-alive\r\n\r\n"
    ).format(GATEWAY_IP, length)
    s.send(entete.encode())

    mycam.SPI_CS_LOW()
    mycam.set_fifo_burst()

    buf = bytearray(CHUNK_SIZE)
    mv = memoryview(buf)
    envoye = 0
    while envoye < length:
        n = CHUNK_SIZE if (length - envoye) >= CHUNK_SIZE else (length - envoye)
        mycam.spi.readinto(mv[:n])
        s.send(mv[:n])
        envoye += n

    mycam.SPI_CS_HIGH()
    mycam.clear_fifo_flag()


def main():
    led.value(0)
    connecter_wifi()
    for _ in range(3):
        led.value(1)
        time.sleep(0.2)
        led.value(0)
        time.sleep(0.2)

    mqtt_client = connecter_mqtt()

    mycam = ArducamClass(OV5642)
    mycam.Camera_Detection()
    mycam.Spi_Test()
    mycam.Camera_Init()
    mycam.set_format(JPEG)
    mycam.OV5642_set_JPEG_size(OV5642_320x240)
    mycam.OV5642_set_Compress_quality(low_quality)
    time.sleep(1)
    mycam.clear_fifo_flag()

    print("Systeme pret - streaming camera + relais capteurs MSP432 actifs")
    led.value(1)

    compteur = 0
    echecs_consecutifs = 0
    t_mesure = time.ticks_ms()
    s = None

    while True:
        wlan = network.WLAN(network.STA_IF)
        if not wlan.isconnected():
            led.value(0)
            if s:
                try:
                    s.close()
                except OSError:
                    pass
                s = None
            connecter_wifi()
            try:
                mqtt_client = connecter_mqtt()
            except OSError as e:
                print("Reconnexion MQTT echouee:", e)
            led.value(1)

        # --- MSP432 : relais UART -> MQTT, non-bloquant, a chaque tour ---
        try:
            lire_msp432_et_publier(mqtt_client)
        except OSError as e:
            print("Erreur MQTT pendant relais MSP432, reconnexion:", e)
            try:
                mqtt_client = connecter_mqtt()
            except OSError as e2:
                print("Reconnexion MQTT echouee:", e2)

        # --- Camera : capture + envoi continu (streaming, prioritaire) ---
        if s is None:
            try:
                s = ouvrir_connexion_gateway()
            except OSError as e:
                print("Connexion au gateway echouee:", e)
                time.sleep(1)
                continue

        mycam.flush_fifo()
        mycam.clear_fifo_flag()
        mycam.start_capture()

        t_debut_capture = time.ticks_ms()
        while not mycam.get_bit(ARDUCHIP_TRIG, CAP_DONE_MASK):
            time.sleep_ms(1)
            if time.ticks_diff(time.ticks_ms(), t_debut_capture) > 2000:
                break

        length = mycam.read_fifo_length()

        if 0 < length < 512000:
            try:
                envoyer_image(s, mycam, length)
                _lire_reponse(s)
                echecs_consecutifs = 0
            except OSError as e:
                print("Erreur connexion gateway (reconnexion au prochain tour):", e)
                try:
                    s.close()
                except OSError:
                    pass
                s = None
                echecs_consecutifs += 1
        else:
            echecs_consecutifs += 1

        compteur += 1

        if compteur % INTERVALLE_GC == 0:
            gc.collect()
            duree = time.ticks_diff(time.ticks_ms(), t_mesure)
            fps = (INTERVALLE_GC * 1000) / duree if duree > 0 else 0
            print("Frames: {} | FPS reel: {:.1f} | RAM libre: {}".format(
                compteur, fps, gc.mem_free()))
            t_mesure = time.ticks_ms()

        if echecs_consecutifs >= 5:
            led.value(0)
            time.sleep(1)
            led.value(1)
            echecs_consecutifs = 0

        if DELAI_ENTRE_FRAMES_MS > 0:
            time.sleep_ms(DELAI_ENTRE_FRAMES_MS)


main()
