"""
Mini-système de construction du dataset — ÉTAPE 1.

Tourne sur son propre port (5001 par défaut) pour rester séparé du
gateway principal. Accessible depuis un navigateur PC OU téléphone :
sur mobile, le bouton "photo" ouvre directement l'appareil photo natif
(attribut HTML capture), donc pas besoin d'installer quoi que ce soit
ni d'autoriser l'accès caméra JavaScript (qui de toute façon ne
fonctionne pas en HTTP simple, seulement en HTTPS/localhost).

Usage :
    python capture_data.py
Puis ouvrir http://IP_DE_LA_VM:5001 depuis un téléphone ou PC.
"""

import os
import cv2
import numpy as np
from flask import Flask, request, render_template, jsonify

import config

app = Flask(__name__)
cascade = cv2.CascadeClassifier(config.CHEMIN_CASCADE)


def _compter_photos(dossier):
    if not os.path.isdir(dossier):
        return 0
    return len([f for f in os.listdir(dossier) if f.lower().endswith((".jpg", ".jpeg", ".png"))])


@app.route("/")
def index():
    return render_template("enroll.html")


@app.route("/api/personnes")
def api_personnes():
    def lister(d):
        if not os.path.isdir(d):
            return []
        return sorted([n for n in os.listdir(d) if os.path.isdir(os.path.join(d, n))])
    return jsonify({
        "autorises": lister(config.DOSSIER_REFERENCE),
        "refuses": lister(config.DOSSIER_REFUSES),
    })


@app.route("/enroll", methods=["POST"])
def enroll():
    nom = request.form.get("nom", "").strip()
    type_personne = request.form.get("type", "").strip()  # "autorise" | "refuse"
    fichiers = request.files.getlist("photos")

    if not nom or type_personne not in ("autorise", "refuse") or not fichiers:
        return jsonify({"succes": False, "message": "Nom, type et au moins une photo sont requis."}), 400

    dossier_base = config.DOSSIER_REFERENCE if type_personne == "autorise" else config.DOSSIER_REFUSES
    dossier_personne = os.path.join(dossier_base, nom)
    os.makedirs(dossier_personne, exist_ok=True)

    deja = _compter_photos(dossier_personne)
    enregistrees = 0
    sans_visage = 0

    for i, fichier in enumerate(fichiers):
        data = fichier.read()
        if not data:
            continue
        nparr = np.frombuffer(data, np.uint8)
        image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if image is None:
            continue

        gris = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        gris = cv2.equalizeHist(gris)
        rects = cascade.detectMultiScale(gris, scaleFactor=1.1, minNeighbors=5, minSize=config.TAILLE_MIN_VISAGE)

        if len(rects) == 0:
            sans_visage += 1
            continue

        x, y, w, h = sorted(rects, key=lambda r: r[2] * r[3], reverse=True)[0]
        visage = cv2.resize(gris[y:y + h, x:x + w], config.TAILLE_VISAGE_MODELE)

        chemin = os.path.join(dossier_personne, f"{nom}_{deja + enregistrees:04d}.jpg")
        cv2.imwrite(chemin, visage)
        enregistrees += 1

    total = _compter_photos(dossier_personne)
    return jsonify({
        "succes": True,
        "enregistrees": enregistrees,
        "sans_visage": sans_visage,
        "total_personne": total,
        "message": f"{enregistrees} photo(s) enregistrée(s) pour {nom} ({total} au total)."
                    + (f" {sans_visage} photo(s) ignorée(s) (aucun visage détecté)." if sans_visage else ""),
    })


if __name__ == "__main__":
    print(f"Mini-outil de construction du dataset sur le port {config.CAPTURE_PORT}")
    print(f"Ouvre http://<IP_DE_LA_VM>:{config.CAPTURE_PORT} depuis un navigateur ou un telephone.")
    app.run(host="0.0.0.0", port=config.CAPTURE_PORT, debug=False)
