"""Applica le migrazioni dello schema al database e mostra la versione.

    python scripts/migrate.py [percorso.db]       (di default FINANCE_DB o data/finance.db)

L'app le applica comunque da sola all'avvio: questo comando serve per farlo (o controllarlo) a mano,
per esempio prima di un aggiornamento.
"""
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import migrations
from config import Config


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else Config.FINANCE_DB
    before = sqlite3.connect(path).execute('PRAGMA user_version').fetchone()[0] if os.path.exists(path) else 0
    applied = migrations.migrate(path)
    print(f'{path}: versione {before} -> {migrations.LATEST}' + (f' ({len(applied)} migrazioni)' if applied else ' (già aggiornato)'))


if __name__ == '__main__':
    main()
