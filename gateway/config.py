"""
Configuration du gateway. Toutes les valeurs sensibles viennent de .env
(copie .env.example en .env et remplis-le — jamais d'identifiants en dur).
"""

import os
import cv2
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# --- Réseau ---
GATEWAY_HOST = os.getenv("GATEWAY_HOST", "0.0.0.0")
GATEWAY_PORT = int(os.getenv("GATEWAY_PORT", "5000"))
CAPTURE_PORT = int(os.getenv("CAPTURE_PORT", "5001"))  # mini-outil de construction du dataset

# --- Dossiers ---
DOSSIER_CAPTURES = os.path.join(BASE_DIR, "captures")
DOSSIER_REFERENCE = os.path.join(BASE_DIR, "dataset", "reference")
DOSSIER_REFUSES = os.path.join(BASE_DIR, "dataset", "refuses")
DOSSIER_MODELE = os.path.join(BASE_DIR, "model")
CHEMIN_MODELE_LBPH = os.path.join(DOSSIER_MODELE, "lbph_model.yml")
CHEMIN_LABELS = os.path.join(DOSSIER_MODELE, "labels.json")
CHEMIN_DB = os.path.join(BASE_DIR, "historique.db")

# --- Détection / reconnaissance ---
CHEMIN_CASCADE = os.path.join(cv2.data.haarcascades, "haarcascade_frontalface_default.xml")
SEUIL_CONFIANCE_LBPH = float(os.getenv("SEUIL_CONFIANCE_LBPH", "70"))
TAILLE_MIN_VISAGE = (60, 60)
TAILLE_VISAGE_MODELE = (200, 200)

# --- Streaming "live" ---
# Intervalle de re-envoi de la derniere frame sur /video_feed. Maintenant que
# l'ESP32 envoie en continu (plus une image toutes les 5s), on peut suivre
# de bien plus pres le rythme reel des frames recues.
STREAM_INTERVAL_SEC = 0.08

# --- Email d'alerte / confirmation ---
EMAIL_EXPEDITEUR = os.getenv("EMAIL_EXPEDITEUR", "")
EMAIL_MOT_DE_PASSE = os.getenv("EMAIL_MOT_DE_PASSE", "")
EMAIL_DESTINATAIRE = os.getenv("EMAIL_DESTINATAIRE", "")
SMTP_SERVEUR = os.getenv("SMTP_SERVEUR", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
IMAP_SERVEUR = os.getenv("IMAP_SERVEUR", "imap.gmail.com")
DELAI_VERIF_EMAILS = int(os.getenv("DELAI_VERIF_EMAILS", "20"))
DELAI_MIN_ENTRE_ALERTES = int(os.getenv("DELAI_MIN_ENTRE_ALERTES", "180"))

# --- MQTT (telemetrie MSP432 relayee par l'ESP32) ---
MQTT_BROKER = os.getenv("MQTT_BROKER", "127.0.0.1")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_CLIENT_ID = os.getenv("MQTT_CLIENT_ID", "gateway_netguard")
TOPIC_CAPTEURS = os.getenv("TOPIC_CAPTEURS", "network/node1/telemetry/msp432")
