"""Crea un utente (o ne cambia la password).

    python scripts/add_user.py nome                  chiede la password (due volte, non visibile)
    python scripts/add_user.py demo --demo           crea l'account demo: dati FITTIZI, sola lettura
    python scripts/add_user.py nome --reset          cambia la password di un utente esistente
    python scripts/add_user.py nome --password XXX   password sulla riga di comando (sconsigliato: resta nella cronologia)

Opera direttamente sul database (FINANCE_DB o data/finance.db): non serve l'app in esecuzione. C'è
registrazione pubblica anche da /registrati. Le password devono avere almeno 8 caratteri.
"""
import argparse
import getpass
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from werkzeug.security import generate_password_hash

import demo_data
from db import connect_raw, finance_db, init_db


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('username')
    ap.add_argument('--demo', action='store_true', help="account demo: dati fittizi, sola lettura")
    ap.add_argument('--reset', action='store_true', help="cambia la password di un utente esistente")
    ap.add_argument('--password', help="password (altrimenti la chiede)")
    ap.add_argument('--email', help="email dell'utente (considerata già verificata: la indica chi amministra)")
    args = ap.parse_args()

    username = args.username.strip().lower()
    email = ''
    if args.email:
        email = args.email.strip().lower()
        if '@' not in email or len(email) > 254 or ' ' in email:
            sys.exit('Email non valida.')
    min_len = 8
    if not username or len(username) > 80:
        sys.exit('Nome utente non valido.')
    pw = args.password or getpass.getpass('Password: ')
    if len(pw) < min_len:
        sys.exit(f'La password deve avere almeno {min_len} caratteri.')
    if not args.password and pw != getpass.getpass('Ripeti la password: '):
        sys.exit('Le due password non coincidono.')

    init_db(log=print)
    with connect_raw() as conn:
        row = conn.execute('SELECT id, is_demo FROM users WHERE username=? COLLATE NOCASE', (username,)).fetchone()
        h = generate_password_hash(pw)
        if email and conn.execute("SELECT 1 FROM users WHERE email=? COLLATE NOCASE AND username != ? COLLATE NOCASE",
                                  (email, username)).fetchone():
            sys.exit(f"L'email {email} è già usata da un altro utente.")
        if row and not args.reset:
            sys.exit(f"L'utente «{username}» esiste già (usa --reset per cambiare la password).")
        if row:
            conn.execute('UPDATE users SET password_hash=? WHERE id=?', (h, row[0]))
            if email:
                conn.execute('UPDATE users SET email=?, email_verified=1 WHERE id=?', (email, row[0]))
            print(f"Password di «{username}» aggiornata: le sue sessioni aperte non valgono più.")
            return
        uid = conn.execute('INSERT INTO users (username, password_hash, is_demo, email, email_verified) '
                           'VALUES (?,?,?,?,?) RETURNING id', (username, h, int(args.demo), email, int(bool(email)))).fetchone()[0]
    # I dati dell'utente con una connessione sua (con PostgreSQL la Row-Level Security lo esige).
    with finance_db(user_id=uid) as conn:
        if args.demo:
            demo_data.populate(conn, uid)
            from datetime import date
            conn.execute('UPDATE users SET data_date=? WHERE id=?', (date.today().isoformat(), uid))
        else:
            demo_data.seed_categories(conn, uid)           # categorie di partenza, modificabili in Impostazioni
        conn.commit()
        print(f"Utente «{username}» creato (id {uid})" + (' — account demo con dati fittizi, in sola lettura.' if args.demo else '.'))


if __name__ == '__main__':
    main()
