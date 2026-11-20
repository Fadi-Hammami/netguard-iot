import sqlite3
from contextlib import contextmanager
from datetime import datetime
import config


@contextmanager
def connexion():
    conn = sqlite3.connect(config.CHEMIN_DB)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with connexion() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS historique (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                horodatage TEXT NOT NULL,
                fichier_image TEXT NOT NULL,
                statut TEXT NOT NULL,        -- autorise | refuse | inconnu
                nom TEXT,
                confiance REAL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS en_attente (
                id TEXT PRIMARY KEY,
                fichier_image TEXT NOT NULL,
                horodatage TEXT NOT NULL,
                historique_id INTEGER
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS telemetrie (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                horodatage TEXT NOT NULL,
                temperature REAL,
                humidite REAL,
                son INTEGER,
                lumiere INTEGER,
                pir INTEGER,
                alerte TEXT
            )
        """)


def ajouter_historique(fichier_image, statut, nom=None, confiance=None):
    horodatage = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with connexion() as conn:
        cur = conn.execute(
            "INSERT INTO historique (horodatage, fichier_image, statut, nom, confiance) "
            "VALUES (?, ?, ?, ?, ?)",
            (horodatage, fichier_image, statut, nom, confiance),
        )
        return cur.lastrowid


def lister_historique(limite=50, statut=None):
    with connexion() as conn:
        if statut:
            rows = conn.execute(
                "SELECT * FROM historique WHERE statut = ? ORDER BY id DESC LIMIT ?",
                (statut, limite),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM historique ORDER BY id DESC LIMIT ?", (limite,)
            ).fetchall()
        return [dict(r) for r in rows]


def stats():
    with connexion() as conn:
        row = conn.execute("""
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN statut='autorise' THEN 1 ELSE 0 END) AS autorises,
                SUM(CASE WHEN statut='refuse' THEN 1 ELSE 0 END) AS refuses,
                SUM(CASE WHEN statut='inconnu' THEN 1 ELSE 0 END) AS inconnus
            FROM historique
        """).fetchone()
        return {
            "total": row["total"] or 0,
            "autorises": row["autorises"] or 0,
            "refuses": row["refuses"] or 0,
            "inconnus": row["inconnus"] or 0,
        }


def ajouter_en_attente(id_unique, fichier_image, historique_id):
    horodatage = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with connexion() as conn:
        conn.execute(
            "INSERT INTO en_attente (id, fichier_image, horodatage, historique_id) "
            "VALUES (?, ?, ?, ?)",
            (id_unique, fichier_image, horodatage, historique_id),
        )


def obtenir_en_attente(id_unique):
    with connexion() as conn:
        row = conn.execute("SELECT * FROM en_attente WHERE id = ?", (id_unique,)).fetchone()
        return dict(row) if row else None


def supprimer_en_attente(id_unique):
    with connexion() as conn:
        conn.execute("DELETE FROM en_attente WHERE id = ?", (id_unique,))


def maj_statut_historique(historique_id, statut, nom):
    with connexion() as conn:
        conn.execute(
            "UPDATE historique SET statut = ?, nom = ? WHERE id = ?",
            (statut, nom, historique_id),
        )


def ajouter_telemetrie(temperature, humidite, son, lumiere, pir, alerte="AUCUNE"):
    horodatage = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with connexion() as conn:
        conn.execute(
            "INSERT INTO telemetrie (horodatage, temperature, humidite, son, lumiere, pir, alerte) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (horodatage, temperature, humidite, son, lumiere,
             None if pir is None else int(bool(pir)), alerte),
        )


def derniere_telemetrie():
    with connexion() as conn:
        row = conn.execute("SELECT * FROM telemetrie ORDER BY id DESC LIMIT 1").fetchone()
        return dict(row) if row else None


def lister_telemetrie(limite=50):
    with connexion() as conn:
        rows = conn.execute(
            "SELECT * FROM telemetrie ORDER BY id DESC LIMIT ?", (limite,)
        ).fetchall()
        return [dict(r) for r in rows]
