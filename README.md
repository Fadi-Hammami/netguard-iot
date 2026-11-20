# NetGuard-IoT
Plateforme IoT de supervision environnementale et de contrôle d'accès avec Edge AI (reconnaissance faciale OpenCV) sur Raspberry Pi.

MSP432 (capteurs) → UART → ESP32 + ArduCAM → MQTT / HTTP → Raspberry Pi 3B+ (Flask, OpenCV, SQLite) → Dashboard web

- `firmware-msp432/` : code C (capteurs, règles d'alerte, buzzer)
- `firmware-esp32/` : MicroPython (caméra, relais UART → MQTT)
- `gateway/` : serveur Flask, reconnaissance faciale, MQTT, dashboard
- `DESCRIPTION.txt` : description détaillée du projet

Auteur : Fedi Hammami, ENIT, stage Telnet Holding (2026)
