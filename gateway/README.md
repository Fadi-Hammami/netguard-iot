# Gateway NetGuard-IoT (Raspberry Pi)

Passerelle de la plateforme NetGuard-IoT : reçoit les images de l'ESP32 + ArduCAM (HTTP),
reconnaît les visages en local (Edge AI : OpenCV Haar Cascade + LBPH), reçoit les mesures
du MSP432 relayées par l'ESP32 (MQTT), et expose un tableau de bord web.

## Architecture

MSP432 (capteurs) → UART → ESP32 + ArduCAM → MQTT / HTTP → **Gateway (Flask, OpenCV, SQLite)** → Dashboard

## Structure

```
gateway2/
├── app.py              programme principal (Flask, /upload, dashboard, API)
├── config.py           configuration (.env)
├── db.py               base SQLite (historique, en_attente, telemetrie)
├── face_engine.py      détection Haar + reconnaissance LBPH
├── mqtt_listener.py    abonné MQTT (télémétrie MSP432)
├── email_alerts.py     alertes + réponses ACCEPTER / REFUSER
├── capture_data.py     ÉTAPE 1 — outil web de construction du dataset
├── train_model.py      ÉTAPE 2 — entraînement du modèle
├── templates/          dashboard, historique, enrôlement
├── dataset/            photos de référence (non publiées)
└── model/              modèle LBPH entraîné (non publié)
```

## Installation

```bash
sudo apt update
sudo apt install -y python3-pip python3-venv mosquitto mosquitto-clients

cd gateway2
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
nano .env        # renseigner MQTT et email
```

## Utilisation

1. `python capture_data.py` puis ouvrir `http://IP_DU_PI:5001` : ajouter des photos de personnes autorisées / refusées.
2. `python train_model.py` : entraîner le modèle.
3. `python app.py` puis ouvrir `http://IP_DU_PI:5000` : tableau de bord.

## Fonctionnement

1. L'ESP32 envoie des images JPEG en POST sur `/upload`.
2. Pas de visage : image affichée dans le flux, rien n'est enregistré.
3. Visage détecté : reconnaissance LBPH
   - connu + autorisé : « Autorisé » (vert)
   - connu + refusé : « Refusé » (rouge)
   - inconnu : « Inconnu » (orange) + email d'alerte
4. Répondre à l'email par `ACCEPTER Nom` ou `REFUSER Nom` met à jour le modèle immédiatement.
5. Le MSP432 envoie des trames JSON (temp, hum, son, lum, pir, alerte) via l'ESP32 sur le topic MQTT `network/node1/telemetry/msp432` ; elles sont stockées en base et affichées en temps réel.

## Réglages utiles

- `SEUIL_CONFIANCE_LBPH` (`.env`) : plus bas = plus strict, plus haut = plus permissif.
- `MQTT_BROKER` : adresse du broker Mosquitto (`127.0.0.1` s'il tourne sur le même Pi).

## Démarrage automatique (systemd)

Créer `/etc/systemd/system/netguard.service` :

```ini
[Unit]
Description=NetGuard-IoT Gateway
After=network-online.target mosquitto.service
Wants=network-online.target

[Service]
User=VOTRE_UTILISATEUR
WorkingDirectory=/chemin/vers/gateway2
ExecStart=/chemin/vers/gateway2/venv/bin/python app.py
Restart=on-failure

[Install]
WantedBy=multi-user.target
```
puis `sudo systemctl enable --now netguard`.
