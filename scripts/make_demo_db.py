"""Crea un database SQLite pieno di dati fittizi (nessun dato reale), per demo e screenshot.

    python scripts/make_demo_db.py demo.db
    FINANCE_LOCAL=1 FINANCE_DB=demo.db python app.py

Il database è creato con le stesse migrazioni dell'app; i dati sono quelli di `demo_data.py`, intestati
all'utente 1. Senza utenti registrati, in modalità locale l'app entra direttamente come quell'utente.
"""
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import demo_data
import migrations


def main(path):
    if os.path.exists(path):
        os.remove(path)
    migrations.migrate(path, log=lambda *_: None)
    conn = sqlite3.connect(path)
    demo_data.populate(conn, 1)
    conn.commit()
    conn.close()
    print(f'Demo database written to {path}')


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else 'demo.db')
