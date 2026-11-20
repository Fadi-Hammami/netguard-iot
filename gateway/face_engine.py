"""
Moteur de détection et reconnaissance faciale.

Détection : Haar Cascade.
Reconnaissance : LBPH.

Point clé (inspiré du projet Raspberry Pi de référence) : quand l'admin
répond ACCEPTER/REFUSER par email, le modèle est mis à jour DIRECTEMENT
EN MÉMOIRE via recognizer.update() — pas besoin de tout réentraîner
depuis le disque, la nouvelle personne est reconnue immédiatement.
Le disque est quand même mis à jour en parallèle pour que ça survive
à un redémarrage du gateway.
"""

import os
import json
import threading
import cv2
import numpy as np
import config

_lock = threading.Lock()


class FaceEngine:
    def __init__(self):
        self.cascade = cv2.CascadeClassifier(config.CHEMIN_CASCADE)
        if self.cascade.empty():
            raise RuntimeError("Impossible de charger la cascade Haar : " + config.CHEMIN_CASCADE)

        self.recognizer = cv2.face.LBPHFaceRecognizer_create()
        self.labels = {}          # {label_id: {"nom": str, "statut": "autorise"/"refuse"}}
        self.prochain_label = 0
        self.modele_charge = False

        self.charger_modele()

    # ------------------------------------------------------------------
    def detecter_visages(self, image_bgr):
        gris = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
        gris = cv2.equalizeHist(gris)
        rects = self.cascade.detectMultiScale(
            gris, scaleFactor=1.1, minNeighbors=5, minSize=config.TAILLE_MIN_VISAGE
        )
        rects = sorted(rects, key=lambda r: r[2] * r[3], reverse=True)
        return gris, rects

    # ------------------------------------------------------------------
    def charger_modele(self):
        with _lock:
            if os.path.exists(config.CHEMIN_MODELE_LBPH) and os.path.exists(config.CHEMIN_LABELS):
                self.recognizer.read(config.CHEMIN_MODELE_LBPH)
                with open(config.CHEMIN_LABELS, "r", encoding="utf-8") as f:
                    brut = json.load(f)
                self.labels = {int(k): v for k, v in brut.items()}
                self.prochain_label = max(self.labels.keys(), default=-1) + 1
                self.modele_charge = True
            else:
                self.modele_charge = False

    def reconnaitre(self, visage_gris):
        """Retourne (statut, nom, confiance). 'inconnu' si pas de modèle ou pas de match fiable."""
        with _lock:
            if not self.modele_charge or not self.labels:
                return "inconnu", None, None

            visage = cv2.resize(visage_gris, config.TAILLE_VISAGE_MODELE)
            visage = cv2.equalizeHist(visage)
            label_id, confiance = self.recognizer.predict(visage)

            info = self.labels.get(label_id)
            if info is None or confiance > config.SEUIL_CONFIANCE_LBPH:
                return "inconnu", None, confiance
            return info["statut"], info["nom"], confiance

    # ------------------------------------------------------------------
    def mettre_a_jour_incremental(self, nom, statut, visage_gris):
        """
        Ajoute IMMÉDIATEMENT une personne au modèle en mémoire (sans tout
        réentraîner). Persiste aussi sur disque (modèle + labels.json)
        pour que ça survive à un redémarrage.
        """
        with _lock:
            visage = cv2.resize(visage_gris, config.TAILLE_VISAGE_MODELE)
            visage = cv2.equalizeHist(visage)
            label_id = self.prochain_label

            try:
                if self.modele_charge:
                    self.recognizer.update([visage], np.array([label_id]))
                else:
                    self.recognizer.train([visage], np.array([label_id]))
                    self.modele_charge = True
            except Exception:
                # Cas rare : recognizer jamais entraîné et update() échoue -> train()
                self.recognizer.train([visage], np.array([label_id]))
                self.modele_charge = True

            self.labels[label_id] = {"nom": nom, "statut": statut}
            self.prochain_label += 1

            os.makedirs(config.DOSSIER_MODELE, exist_ok=True)
            self.recognizer.save(config.CHEMIN_MODELE_LBPH)
            with open(config.CHEMIN_LABELS, "w", encoding="utf-8") as f:
                json.dump(self.labels, f, ensure_ascii=False, indent=2)

    # ------------------------------------------------------------------
    @staticmethod
    def entrainer_complet():
        """
        Reconstruit le modèle EN ENTIER depuis dataset/reference et
        dataset/refuses (structure : dataset/<reference|refuses>/<Nom>/*.jpg).
        Utile après avoir ajouté beaucoup de photos via capture_data.py,
        ou pour repartir d'une base propre.
        """
        cascade = cv2.CascadeClassifier(config.CHEMIN_CASCADE)
        visages, labels_num = [], []
        labels_info = {}
        prochain_id = 0

        for dossier_racine, statut in (
            (config.DOSSIER_REFERENCE, "autorise"),
            (config.DOSSIER_REFUSES, "refuse"),
        ):
            if not os.path.isdir(dossier_racine):
                continue
            for nom_personne in sorted(os.listdir(dossier_racine)):
                chemin_personne = os.path.join(dossier_racine, nom_personne)
                if not os.path.isdir(chemin_personne):
                    continue

                label_id = prochain_id
                prochain_id += 1
                nb_photos = 0

                for fichier in os.listdir(chemin_personne):
                    if not fichier.lower().endswith((".jpg", ".jpeg", ".png")):
                        continue
                    img = cv2.imread(os.path.join(chemin_personne, fichier), cv2.IMREAD_GRAYSCALE)
                    if img is None:
                        continue
                    img = cv2.equalizeHist(img)

                    rects = cascade.detectMultiScale(
                        img, scaleFactor=1.1, minNeighbors=5, minSize=config.TAILLE_MIN_VISAGE
                    )
                    if len(rects) == 0:
                        visage = cv2.resize(img, config.TAILLE_VISAGE_MODELE)
                    else:
                        x, y, w, h = sorted(rects, key=lambda r: r[2] * r[3], reverse=True)[0]
                        visage = cv2.resize(img[y:y + h, x:x + w], config.TAILLE_VISAGE_MODELE)

                    visages.append(visage)
                    labels_num.append(label_id)
                    nb_photos += 1

                if nb_photos > 0:
                    labels_info[label_id] = {"nom": nom_personne, "statut": statut}
                else:
                    prochain_id -= 1

        if not visages:
            return False

        os.makedirs(config.DOSSIER_MODELE, exist_ok=True)
        recognizer = cv2.face.LBPHFaceRecognizer_create()
        recognizer.train(visages, np.array(labels_num))
        recognizer.save(config.CHEMIN_MODELE_LBPH)

        with open(config.CHEMIN_LABELS, "w", encoding="utf-8") as f:
            json.dump(labels_info, f, ensure_ascii=False, indent=2)

        return True
