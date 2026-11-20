import os
import io
import time
import threading
import logging
from datetime import datetime

import cv2
import numpy as np
from flask import Flask, request, render_template, send_from_directory, jsonify, Response

import config
import db
from face_engine import FaceEngine
import email_alerts
import mqtt_listener

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s: %(message)s",
    handlers=[logging.FileHandler("gateway.log"), logging.StreamHandler()],
)
logger = logging.getLogger("gateway")

app = Flask(__name__)

os.makedirs(config.DOSSIER_CAPTURES, exist_ok=True)
os.makedirs(config.DOSSIER_REFERENCE, exist_ok=True)
os.makedirs(config.DOSSIER_REFUSES, exist_ok=True)

db.init_db()
moteur = FaceEngine()
_arret_thread = threading.Event()

# --- État partagé pour le flux "quasi-live" et le statut courant ---
_frame_lock = threading.Lock()
_derniere_frame_jpeg = None   # bytes JPEG de la dernière capture annotée

_event_lock = threading.Lock()
_dernier_evenement = {"type": "attente", "nom": "", "heure": "", "confiance": None}

# Suivi de transition : ne logue en base / ne sauvegarde sur disque / n'alerte
# que lorsque le resultat CHANGE par rapport a la frame precedente. Sans ca,
# en streaming continu, chaque personne genererait des dizaines d'entrees
# identiques par seconde au lieu d'un seul evenement "entree detectee".
_transition_lock = threading.Lock()
_dernier_statut_logge = {"statut": None, "nom": None}

COULEURS = {
    "autorise": (60, 200, 60),
    "refuse": (40, 40, 230),
    "inconnu": (0, 165, 255),
}
LIBELLES = {"autorise": "AUTORISÉ", "refuse": "REFUSÉ", "inconnu": "INCONNU"}


def _construire_frame_annotee(image, rect, statut, nom, confiance):
    x, y, w, h = rect
    couleur = COULEURS.get(statut, (200, 200, 200))
    texte = _sans_accents(LIBELLES.get(statut, statut))
    if nom:
        texte = f"{texte} : {_sans_accents(nom)}"

    annote = image.copy()
    cv2.rectangle(annote, (x, y), (x + w, y + h), couleur, 2)
    cv2.rectangle(annote, (x, max(0, y - 28)), (x + w, y), couleur, -1)
    cv2.putText(annote, texte, (x + 5, y - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1, cv2.LINE_AA)
    cv2.putText(annote, datetime.now().strftime("%H:%M:%S"), (8, 22),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1, cv2.LINE_AA)

    ok, buf = cv2.imencode(".jpg", annote, [cv2.IMWRITE_JPEG_QUALITY, 80])
    return buf.tobytes() if ok else None


def _construire_frame_brute(image):
    """Frame affichée quand la caméra ne voit aucun visage — juste
    l'horodatage, pas de rectangle. Permet de voir le champ de la
    caméra en continu, pas seulement quand quelqu'un est détecté."""
    annote = image.copy()
    cv2.putText(annote, datetime.now().strftime("%H:%M:%S"), (8, 22),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1, cv2.LINE_AA)
    cv2.putText(annote, "Aucun visage", (8, annote.shape[0] - 10),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (150, 150, 170), 1, cv2.LINE_AA)

    ok, buf = cv2.imencode(".jpg", annote, [cv2.IMWRITE_JPEG_QUALITY, 80])
    return buf.tobytes() if ok else None


def _image_placeholder(texte):
    img = np.full((240, 320, 3), (25, 25, 35), dtype=np.uint8)
    cv2.putText(img, texte, (12, 120), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (150, 150, 170), 1, cv2.LINE_AA)
    ok, buf = cv2.imencode(".jpg", img)
    return buf.tobytes() if ok else b""


def _sans_accents(texte):
    """cv2.putText ne gère pas les caractères accentués (ils sortent en '?').
    Utilisé uniquement pour le texte dessiné SUR l'image ; le dashboard,
    la base de données et les emails gardent les accents normalement."""
    import unicodedata
    nfkd = unicodedata.normalize("NFKD", texte)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


# ----------------------------------------------------------------------
# Réception des captures depuis l'ESP32
# ----------------------------------------------------------------------
@app.route("/upload", methods=["POST"])
def upload():
    global _derniere_frame_jpeg, _dernier_evenement

    data = request.get_data()
    if not data:
        return "empty", 400

    nparr = np.frombuffer(data, np.uint8)
    image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    if image is None:
        logger.warning("Image reçue mais non décodable.")
        return "invalid image", 400

    gris, rects = moteur.detecter_visages(image)

    if len(rects) == 0:
        # Personne dans le champ : on reinitialise la transition pour que
        # la prochaine detection (meme si c'est la meme personne qui revient)
        # soit bien traitee comme un nouvel evenement.
        with _transition_lock:
            _dernier_statut_logge["statut"] = None
            _dernier_statut_logge["nom"] = None

        # On affiche quand meme le champ de la camera en continu, meme
        # sans visage -- c'est ca qui donne un flux "live" fluide plutot
        # qu'un flux qui se fige des qu'il n'y a plus personne.
        jpeg = _construire_frame_brute(image)
        if jpeg:
            with _frame_lock:
                _derniere_frame_jpeg = jpeg

        with _event_lock:
            _dernier_evenement = {"type": "attente", "nom": "", "heure": datetime.now().strftime("%H:%M:%S"), "confiance": None}
        return "no face", 200

    x, y, w, h = rects[0]
    visage_gris = gris[y:y + h, x:x + w]
    statut, nom, confiance = moteur.reconnaitre(visage_gris)

    # --- Mis à jour à CHAQUE frame : flux live + statut affiché ---
    jpeg = _construire_frame_annotee(image, (x, y, w, h), statut, nom, confiance)
    if jpeg:
        with _frame_lock:
            _derniere_frame_jpeg = jpeg

    with _event_lock:
        _dernier_evenement = {
            "type": statut,
            "nom": nom or ("Inconnu" if statut == "inconnu" else ""),
            "heure": datetime.now().strftime("%H:%M:%S"),
            "confiance": round(confiance, 1) if confiance is not None else None,
        }

    # --- Enregistré / alerté SEULEMENT si le résultat a changé ---
    with _transition_lock:
        est_nouvelle_transition = (
            statut != _dernier_statut_logge["statut"] or nom != _dernier_statut_logge["nom"]
        )
        if est_nouvelle_transition:
            _dernier_statut_logge["statut"] = statut
            _dernier_statut_logge["nom"] = nom

    if est_nouvelle_transition:
        horodatage = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        nom_fichier = f"capture_{horodatage}.jpg"
        chemin_fichier = os.path.join(config.DOSSIER_CAPTURES, nom_fichier)
        cv2.imwrite(chemin_fichier, image)

        historique_id = db.ajouter_historique(nom_fichier, statut, nom, confiance)
        logger.info(f"Nouvelle transition -> statut={statut} nom={nom} confiance={confiance}")

        if statut == "inconnu":
            id_unique = horodatage
            db.ajouter_en_attente(id_unique, chemin_fichier, historique_id)
            threading.Thread(target=email_alerts.envoyer_alerte, args=(id_unique, chemin_fichier), daemon=True).start()

    return "ok", 200


# ----------------------------------------------------------------------
# Flux "quasi-live" (MJPEG) : rejoue la dernière capture annotée
# ----------------------------------------------------------------------
def _generateur_stream():
    while True:
        with _frame_lock:
            frame = _derniere_frame_jpeg
        if frame is None:
            frame = _image_placeholder("En attente de la premiere capture...")
        yield (b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + frame + b"\r\n")
        time.sleep(config.STREAM_INTERVAL_SEC)


@app.route("/video_feed")
def video_feed():
    return Response(_generateur_stream(), mimetype="multipart/x-mixed-replace; boundary=frame")


# ----------------------------------------------------------------------
# Interface web
# ----------------------------------------------------------------------
@app.route("/")
def dashboard():
    recents = db.lister_historique(limite=12)
    return render_template("dashboard.html", captures=recents, modele_charge=moteur.modele_charge)


@app.route("/historique")
def historique():
    statut_filtre = request.args.get("statut")
    lignes = db.lister_historique(limite=200, statut=statut_filtre)
    return render_template("historique.html", captures=lignes, statut_filtre=statut_filtre)


@app.route("/api/status")
def api_status():
    with _event_lock:
        return jsonify(_dernier_evenement.copy())


@app.route("/api/stats")
def api_stats():
    return jsonify(db.stats())


@app.route("/api/telemetrie")
def api_telemetrie():
    """Derniere lecture capteurs recue du MSP432 (via ESP32 -> MQTT).
    Utilise d'abord le cache en memoire (mqtt_listener), et retombe sur
    la base de donnees si rien n'a encore ete recu depuis le demarrage."""
    derniere = mqtt_listener.obtenir_derniere_lecture()
    if derniere is None:
        derniere = db.derniere_telemetrie()
    return jsonify(derniere or {})


@app.route("/api/telemetrie/historique")
def api_telemetrie_historique():
    limite = request.args.get("limite", default=50, type=int)
    return jsonify(db.lister_telemetrie(limite=limite))


@app.route("/captures/<path:nom_fichier>")
def servir_capture(nom_fichier):
    return send_from_directory(config.DOSSIER_CAPTURES, nom_fichier)


@app.route("/entrainer", methods=["POST"])
def entrainer():
    ok = FaceEngine.entrainer_complet()
    if ok:
        moteur.charger_modele()
        return jsonify({"succes": True, "message": "Modèle réentraîné depuis le dataset complet."})
    return jsonify({"succes": False, "message": "Aucun visage exploitable trouvé dans dataset/."}), 400


if __name__ == "__main__":
    if not email_alerts.alertes_configurees():
        logger.warning("Config email incomplète (.env) — alertes et réponses ACCEPTER/REFUSER désactivées.")
    else:
        threading.Thread(
            target=email_alerts.verifier_reponses_boucle, args=(moteur, _arret_thread), daemon=True
        ).start()

    threading.Thread(target=mqtt_listener.demarrer_client_mqtt, daemon=True).start()

    logger.info(f"Démarrage du gateway sur {config.GATEWAY_HOST}:{config.GATEWAY_PORT}")
    app.run(host=config.GATEWAY_HOST, port=config.GATEWAY_PORT, debug=False, threaded=True)
