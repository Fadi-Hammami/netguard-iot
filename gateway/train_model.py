#!/usr/bin/env python3
"""
ÉTAPE 2 — Entraînement du modèle LBPH.

Usage :
    python train_model.py

À relancer chaque fois que tu as ajouté beaucoup de nouvelles photos
via capture_data.py (les décisions ACCEPTER/REFUSER par email, elles,
mettent déjà à jour le modèle immédiatement, ce script n'est pas
obligatoire pour elles — il sert surtout pour un premier entraînement
en masse ou une reconstruction propre).
"""

from face_engine import FaceEngine


def main():
    print("=" * 50)
    print("  ENTRAÎNEMENT DU MODÈLE LBPH")
    print("=" * 50)

    ok = FaceEngine.entrainer_complet()

    if ok:
        print("\n✓ Modèle entraîné et sauvegardé avec succès.")
        print("  → Relance (ou laisse tourner) app.py pour utiliser le nouveau modèle.")
    else:
        print("\n✗ Aucun visage exploitable trouvé.")
        print("  Vérifie qu'il y a bien des photos dans :")
        print("    dataset/reference/<Nom>/*.jpg")
        print("    dataset/refuses/<Nom>/*.jpg")
        print("  → Utilise capture_data.py pour en ajouter.")


if __name__ == "__main__":
    main()
