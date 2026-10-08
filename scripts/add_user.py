"""Crea un utente (o ne cambia la password).

    python scripts/add_user.py nome                  chiede la password (due volte, non visibile)
    python scripts/add_user.py demo --demo           crea l'account demo: dati FITTIZI, sola lettura
    python scripts/add_user.py nome --reset          cambia la password di un utente esistente
    python scripts/add_user.py nome --password XXX   password sulla riga di comando (sconsigliato: resta nella cronologia)

Opera direttamente sul database (FINANCE_DB o data/finance.db): non serve l'app in esecuzione. Non c'è
registrazione pubblica: gli utenti si creano solo da qui. Le password devono avere almeno 10 caratteri
(8 per l'account demo, che è pubblico e protegge solo dati finti).
"""
import argparse
import getpass
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from werkzeug.security import generate_password_hash

import demo_data
import migrations
from config import Config


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('username')
    ap.add_argument('--demo', action='store_true', help="account demo: dati fittizi, sola lettura")
    ap.add_argument('--reset', action='store_true', help="cambia la password di un utente esistente")
    ap.add_argument('--password', help="password (altrimenti la chiede)")
    args = ap.parse_args()

    username = args.username.strip().lower()
    min_len = 8 if args.demo else 10
    if not username or len(username) > 80:
        sys.exit('Nome utente non valido.')
    pw = args.password or getpass.getpass('Password: ')
    if len(pw) < min_len:
        sys.exit(f'La password deve avere almeno {min_len} caratteri.')
    if not args.password and pw != getpass.getpass('Ripeti la password: '):
        sys.exit('Le due password non coincidono.')

    migrations.migrate(Config.FINANCE_DB, log=print)
    with sqlite3.connect(Config.FINANCE_DB) as conn:
        row = conn.execute('SELECT id, is_demo FROM users WHERE username=? COLLATE NOCASE', (username,)).fetchone()
        h = generate_password_hash(pw)
        if row and not args.reset:
            sys.exit(f"L'utente «{username}» esiste già (usa --reset per cambiare la password).")
        if row:
            conn.execute('UPDATE users SET password_hash=? WHERE id=?', (h, row[0]))
            print(f"Password di «{username}» aggiornata: le sue sessioni aperte non valgono più.")
            return
        cur = conn.execute('INSERT INTO users (username, password_hash, is_demo) VALUES (?,?,?)', (username, h, int(args.demo)))
        uid = cur.lastrowid
        if args.demo:
            demo_data.populate(conn, uid)
            from datetime import date
            conn.execute('UPDATE users SET data_date=? WHERE id=?', (date.today().isoformat(), uid))
        else:
            demo_data.seed_categories(conn, uid)           # categorie di partenza, modificabili in Impostazioni
        print(f"Utente «{username}» creato (id {uid})" + (' — account demo con dati fittizi, in sola lettura.' if args.demo else '.'))


if __name__ == '__main__':
    main()
