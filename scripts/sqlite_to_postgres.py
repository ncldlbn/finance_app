"""Copia un database SQLite di Finance Tracker in PostgreSQL.

    DATABASE_OWNER_URL=postgresql://proprietario:password@host:5432/nome python scripts/sqlite_to_postgres.py data/finance.db

Con docker compose (il file SQLite va reso visibile al container, es. con la cartella data/ montata):

    docker compose run --rm -v "$PWD/data:/data" migrate python scripts/sqlite_to_postgres.py /data/finance.db

Usa il PROPRIETARIO del database (scrive i dati di tutti gli utenti, cosa che l'utente dell'app non può fare per
via della Row-Level Security). Passi: porta il file SQLite all'ultima migrazione (con il backup automatico),
porta PostgreSQL all'ultima versione, copia ogni tabella con gli stessi id, riallinea i contatori degli id e
confronta righe e totali delle due basi. I vincoli di PostgreSQL controllano ogni riga copiata: se un dato non è
valido la copia si ferma e non lascia niente a metà.
Si rifiuta di scrivere su un PostgreSQL che contiene già utenti, a meno di --replace (che lo svuota prima).
"""
import argparse
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

TABLES = ['users', 'category', 'expenses', 'incomes', 'budgets', 'planned_expenses', 'recurring_expenses',
          'wealth_slots', 'wealth_group_settings', 'wealth_values', 'patrimonio', 'settings', 'login_attempts']
PERSONAL = ['category', 'expenses', 'incomes', 'budgets', 'planned_expenses', 'recurring_expenses',
            'wealth_slots', 'wealth_group_settings', 'wealth_values', 'patrimonio']
SEQUENCES = ('users', 'category', 'expenses', 'incomes', 'planned_expenses', 'recurring_expenses', 'patrimonio')
# Colonne di cui confrontare la somma, oltre al numero di righe.
SUMS = {'expenses': 'euro', 'incomes': 'euro', 'budgets': 'value', 'planned_expenses': 'euro',
        'recurring_expenses': 'euro', 'wealth_values': 'value'}


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('sqlite_file')
    ap.add_argument('--replace', action='store_true', help='svuota PostgreSQL prima di copiare')
    args = ap.parse_args()
    owner_url = os.environ.get('DATABASE_OWNER_URL')
    if not owner_url:
        sys.exit('Imposta DATABASE_OWNER_URL (postgresql://proprietario:password@host/nome).')
    if not os.path.exists(args.sqlite_file):
        sys.exit(f'File non trovato: {args.sqlite_file}')

    import psycopg
    import migrations
    import migrations_pg
    migrations.migrate(args.sqlite_file, log=print)
    migrations_pg.migrate(owner_url, log=print)

    src = sqlite3.connect(args.sqlite_file)
    exists = lambda t: src.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (t,)).fetchone()
    tables = [t for t in TABLES if exists(t)]
    with psycopg.connect(owner_url) as raw:
        if raw.execute('SELECT COUNT(*) FROM users').fetchone()[0]:
            if not args.replace:
                sys.exit('PostgreSQL contiene già degli utenti: usa --replace per svuotarlo e ricopiare tutto.')
            raw.execute('TRUNCATE ' + ', '.join(TABLES) + ' RESTART IDENTITY CASCADE')
        try:
            for t in tables:
                src_cols = [r[1] for r in src.execute(f'PRAGMA table_info({t})')]
                dst_cols = {r[0] for r in raw.execute('SELECT column_name FROM information_schema.columns '
                                                      'WHERE table_schema=%s AND table_name=%s', ('public', t))}
                cols = [c for c in src_cols if c in dst_cols]
                rows = src.execute(f'SELECT {", ".join(cols)} FROM {t}').fetchall()
                if t == 'users':
                    # created_at vuoto o assente: lo mette PostgreSQL
                    rows = [tuple(None if (c == 'created_at' and not v) else v for c, v in zip(cols, r)) for r in rows]
                with raw.cursor() as cur, cur.copy(f'COPY {t} ({", ".join(cols)}) FROM STDIN') as cp:
                    for r in rows:
                        cp.write_row(r)
                print(f'{t:24} {len(rows):>7} righe')
                if t == 'users':
                    # Righe personali di id senza utente (vecchi database a utente unico): utenti senza password,
                    # che non possono accedere, perché le chiavi esterne non ammettono righe orfane.
                    ids = set()
                    for p in PERSONAL:
                        if exists(p):
                            ids |= {r[0] for r in src.execute(f'SELECT DISTINCT user_id FROM {p}')}
                    known = {r[0] for r in raw.execute('SELECT id FROM users')}
                    for uid in sorted(ids - known):
                        raw.execute("INSERT INTO users (id, username, password_hash) VALUES (%s, %s, '')",
                                    (uid, f'utente-{uid}'))
                        print(f'{"":24} + utente senza password «utente-{uid}» per i dati dell\'id {uid}')
            for t in SEQUENCES:
                raw.execute(f"SELECT setval(pg_get_serial_sequence('{t}', 'id'), "
                            f"COALESCE((SELECT MAX(id) FROM {t}), 0) + 1, false)")
            raw.commit()
        except psycopg.errors.IntegrityError as e:
            raw.rollback()
            sys.exit(f'Copia annullata, nessun dato scritto: un dato non rispetta i vincoli di PostgreSQL.\n  {e}')

        # Verifica: stesse righe e stessi totali.
        bad = []
        for t in tables:
            a = src.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0]
            b = raw.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0]
            if t == 'users':
                # (COLLATE "C": LIKE non si può usare con l'ordinamento che ignora le maiuscole)
                b -= raw.execute("""SELECT COUNT(*) FROM users WHERE username COLLATE "C" LIKE 'utente-%%' """
                                 "AND password_hash = ''").fetchone()[0]
            if a != b:
                bad.append(f'{t}: {a} righe in SQLite, {b} in PostgreSQL')
            if t in SUMS:
                sa = src.execute(f'SELECT ROUND(COALESCE(SUM({SUMS[t]}), 0), 2) FROM {t}').fetchone()[0]
                sb = raw.execute(f'SELECT ROUND(COALESCE(SUM({SUMS[t]}), 0)::numeric, 2) FROM {t}').fetchone()[0]
                if abs(float(sa) - float(sb)) > 0.005 * max(1, a):
                    bad.append(f'{t}: totale {sa} in SQLite, {sb} in PostgreSQL')
        src.close()
        if bad:
            sys.exit('Copia NON coerente:\n  ' + '\n  '.join(bad))
        print('Copia completata: righe e totali coincidono.')


if __name__ == '__main__':
    main()
