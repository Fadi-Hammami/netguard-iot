import os
import re
import time
import logging
import smtplib
import imaplib
import email as email_lib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage

import config
import db

logger = logging.getLogger("email_alerts")
_dernier_envoi = None


def alertes_configurees():
    return bool(config.EMAIL_EXPEDITEUR and config.EMAIL_MOT_DE_PASSE and config.EMAIL_DESTINATAIRE)


def envoyer_alerte(id_unique, chemin_image):
    global _dernier_envoi
    if not alertes_configurees():
        return

    maintenant = time.time()
    if _dernier_envoi and (maintenant - _dernier_envoi) < config.DELAI_MIN_ENTRE_ALERTES:
        logger.info("Alerte ignorée (anti-spam).")
        return

    try:
        msg = MIMEMultipart("related")
        msg["From"] = config.EMAIL_EXPEDITEUR
        msg["To"] = config.EMAIL_DESTINATAIRE
        msg["Subject"] = f"Alerte Visage Inconnu - ID:{id_unique}"

        html = f"""<html><body style="font-family:Arial,sans-serif">
<h2 style="color:#c0392b">Visage inconnu détecté</h2>
<p><b>ID :</b> {id_unique}</p>
<img src="cid:photo" style="width:360px;border:3px solid #c0392b">
<hr>
<p>Répondez à cet email avec :</p>
<p>✅ <b>ACCEPTER Prenom</b> — autoriser cette personne</p>
<p>❌ <b>REFUSER Prenom</b> — bloquer cette personne</p>
</body></html>"""

        alt = MIMEMultipart("alternative")
        alt.attach(MIMEText(f"Visage inconnu ID:{id_unique}. Répondez ACCEPTER Prenom ou REFUSER Prenom.", "plain"))
        alt.attach(MIMEText(html, "html"))
        msg.attach(alt)

        with open(chemin_image, "rb") as f:
            piece = MIMEImage(f.read())
            piece.add_header("Content-ID", "<photo>")
            piece.add_header("Content-Disposition", "inline", filename="inconnu.jpg")
            msg.attach(piece)

        with smtplib.SMTP(config.SMTP_SERVEUR, config.SMTP_PORT) as s:
            s.starttls()
            s.login(config.EMAIL_EXPEDITEUR, config.EMAIL_MOT_DE_PASSE)
            s.send_message(msg)

        _dernier_envoi = maintenant
        logger.info(f"Alerte envoyée (ID:{id_unique})")

    except Exception as e:
        logger.error(f"Erreur envoi alerte : {e}")


def envoyer_confirmation(nom, accepte):
    if not alertes_configurees():
        return
    try:
        action = "AUTORISÉ" if accepte else "REFUSÉ"
        couleur = "#27ae60" if accepte else "#c0392b"

        msg = MIMEMultipart("alternative")
        msg["From"] = config.EMAIL_EXPEDITEUR
        msg["To"] = config.EMAIL_DESTINATAIRE
        msg["Subject"] = f"Confirmation — {nom} {action}"
        html = f"""<html><body style="font-family:Arial,sans-serif">
<h2 style="color:{couleur}">{nom} {action}</h2>
<p>La reconnaissance a été mise à jour immédiatement, {nom} sera
reconnu(e) dès la prochaine capture.</p>
</body></html>"""
        msg.attach(MIMEText(f"{nom} {action}. Reconnaissance mise à jour.", "plain"))
        msg.attach(MIMEText(html, "html"))

        with smtplib.SMTP(config.SMTP_SERVEUR, config.SMTP_PORT) as s:
            s.starttls()
            s.login(config.EMAIL_EXPEDITEUR, config.EMAIL_MOT_DE_PASSE)
            s.send_message(msg)

        logger.info(f"Confirmation envoyée : {nom} {action}")
    except Exception as e:
        logger.error(f"Erreur envoi confirmation : {e}")


def _extraire_reponse(msg):
    """Isole la vraie réponse de l'admin, en coupant avant le texte cité du client mail."""
    texte = ""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                try:
                    texte = part.get_payload(decode=True).decode("utf-8", errors="ignore")
                    break
                except Exception:
                    pass
    else:
        try:
            texte = msg.get_payload(decode=True).decode("utf-8", errors="ignore")
        except Exception:
            texte = str(msg.get_payload() or "")

    lignes = []
    for ligne in texte.splitlines():
        l = ligne.strip()
        if l.startswith(">"):
            break
        if re.match(r"^(Le |On ).{5,50}(a écrit|wrote)\s*:", l):
            break
        if re.match(r"^-{3,}", l) or re.match(r"^_{3,}", l):
            break
        lignes.append(ligne)
    return "\n".join(lignes).strip()


def _traiter_decision(moteur, id_unique, nom, accepter):
    import cv2
    entree = db.obtenir_en_attente(id_unique)
    if not entree:
        logger.warning(f"ID {id_unique} déjà traité ou introuvable.")
        return

    chemin_source = entree["fichier_image"]
    if not os.path.exists(chemin_source):
        logger.error(f"Image {chemin_source} introuvable.")
        db.supprimer_en_attente(id_unique)
        return

    image = cv2.imread(chemin_source)
    gris, rects = moteur.detecter_visages(image) if image is not None else (None, [])

    dossier_base = config.DOSSIER_REFERENCE if accepter else config.DOSSIER_REFUSES
    dossier_personne = os.path.join(dossier_base, nom)
    os.makedirs(dossier_personne, exist_ok=True)
    import shutil
    shutil.copy(chemin_source, os.path.join(dossier_personne, f"{id_unique}.jpg"))

    statut = "autorise" if accepter else "refuse"
    db.maj_statut_historique(entree["historique_id"], statut, nom)
    db.supprimer_en_attente(id_unique)

    if gris is not None and len(rects) > 0:
        x, y, w, h = rects[0]
        moteur.mettre_a_jour_incremental(nom, statut, gris[y:y + h, x:x + w])
        logger.info(f"Modèle mis à jour EN MÉMOIRE : {nom} -> {statut}")

    envoyer_confirmation(nom, accepter)


def verifier_reponses_boucle(moteur, arret_event):
    if not alertes_configurees():
        return

    while not arret_event.is_set():
        try:
            with imaplib.IMAP4_SSL(config.IMAP_SERVEUR) as mail:
                mail.login(config.EMAIL_EXPEDITEUR, config.EMAIL_MOT_DE_PASSE)
                mail.select("inbox")
                statut, messages = mail.search(None, '(UNSEEN SUBJECT "Alerte Visage Inconnu")')

                if statut == "OK" and messages[0]:
                    for num in messages[0].split():
                        try:
                            st2, data = mail.fetch(num, "(RFC822)")
                            if st2 != "OK":
                                continue
                            msg = email_lib.message_from_bytes(data[0][1])
                            sujet = msg.get("subject", "")
                            m = re.search(r"ID:(\S+)", sujet)
                            if not m:
                                continue
                            id_unique = m.group(1)
                            reponse = _extraire_reponse(msg)
                            haut = reponse.upper()

                            if "ACCEPTER" in haut:
                                mn = re.search(r"ACCEPTER\s+([A-Za-zÀ-ÿ][A-Za-zÀ-ÿ0-9_\-]*)", reponse, re.IGNORECASE)
                                nom = mn.group(1).strip().capitalize() if mn else f"Personne_{id_unique}"
                                _traiter_decision(moteur, id_unique, nom, accepter=True)
                            elif "REFUSER" in haut:
                                mn = re.search(r"REFUSER\s+([A-Za-zÀ-ÿ][A-Za-zÀ-ÿ0-9_\-]*)", reponse, re.IGNORECASE)
                                nom = mn.group(1).strip().capitalize() if mn else f"Refus_{id_unique}"
                                _traiter_decision(moteur, id_unique, nom, accepter=False)

                        finally:
                            try:
                                mail.store(num, "+FLAGS", "\\Seen")
                            except Exception:
                                pass

        except Exception as e:
            logger.error(f"Erreur vérification emails : {e}")

        arret_event.wait(config.DELAI_VERIF_EMAILS)
