"""
Abonne MQTT du gateway. Ecoute le topic sur lequel l'ESP32 relaie les trames
JSON recues du MSP432 par UART, et les insere dans la table `telemetrie`.

Demarre dans un thread daemon depuis app.py.
"""

import json
import logging
from datetime import datetime

import paho.mqtt.client as mqtt

import config
import db

logger = logging.getLogger("gateway")

# Derniere lecture recue (cles identiques a celles attendues par le dashboard)
_derniere_lecture = None


def _on_connect(client, userdata, flags, rc, *args):
    if rc == 0:
        logger.info(f"MQTT connecte au broker {config.MQTT_BROKER}:{config.MQTT_PORT}")
        client.subscribe(config.TOPIC_CAPTEURS)
    else:
        logger.warning(f"Echec de connexion MQTT (code {rc})")


def _on_message(client, userdata, msg):
    global _derniere_lecture

    try:
        payload = json.loads(msg.payload.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as e:
        logger.warning(f"Trame MQTT ignoree (JSON invalide) : {e}")
        return

    lecture = {
        "temperature": payload.get("temp"),
        "humidite": payload.get("hum"),
        "son": payload.get("son"),
        "lumiere": payload.get("lum"),
        "pir": payload.get("pir"),
        "alerte": payload.get("alerte", "AUCUNE"),
        "horodatage": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }

    try:
        db.ajouter_telemetrie(
            lecture["temperature"], lecture["humidite"], lecture["son"],
            lecture["lumiere"], lecture["pir"], lecture["alerte"],
        )
        _derniere_lecture = lecture
        logger.info(f"Telemetrie MSP432 enregistree : {lecture}")
    except Exception as e:
        logger.error(f"Erreur enregistrement telemetrie : {e}")


def obtenir_derniere_lecture():
    """Utilise par /api/telemetrie pour un affichage immediat."""
    return _derniere_lecture


def demarrer_client_mqtt():
    """A appeler une seule fois, dans un thread daemon, au demarrage de app.py."""
    client = mqtt.Client(client_id=config.MQTT_CLIENT_ID)
    client.on_connect = _on_connect
    client.on_message = _on_message
    # reconnexion automatique si le broker redemarre
    client.connect_async(config.MQTT_BROKER, config.MQTT_PORT, keepalive=60)
    client.loop_forever(retry_first_connection=True)
