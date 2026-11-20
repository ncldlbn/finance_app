"""Copia un database SQLite di Finance Tracker in PostgreSQL.

    DATABASE_URL=postgresql://utente:password@host:5432/nome python scripts/sqlite_to_postgres.py data/finance.db

Con docker compose (il file SQLite va reso visibile al container, es. nella cartella data/ montata):

    docker compose run --rm -v "$PWD/data:/data" app python scripts/sqlite_to_postgres.py /data/finance.db

Passi: porta il file SQLite all'ultima migrazione (con il backup automatico), crea lo schema PostgreSQL se
manca, copia ogni tabella con gli stessi id, riallinea i contatori degli id e confronta righe e totali delle due
basi. Si rifiuta di scrivere su un PostgreSQL che contiene già utenti, a meno di --replace (che lo svuota prima).
"""
import argparse
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

TABLES = ['users', 'category', 'expenses', 'incomes', 'budgets', 'planned_expenses', 'recurring_expenses',
          'wealth_slots', 'wealth_group_settings', 'wealth_values', 'patrimonio', 'settings', 'login_attempts']
# Colonne di cui confrontare la somma, oltre al numero di righe.
SUMS = {'expenses': 'euro', 'incomes': 'euro', 'budgets': 'value', 'planned_expenses': 'euro',
        'recurring_expenses': 'euro', 'wealth_values': 'value'}


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('sqlite_file')
    ap.add_argument('--replace', action='store_true', help='svuota PostgreSQL prima di copiare')
    args = ap.parse_args()
    if not os.environ.get('DATABASE_URL'):
        sys.exit('Imposta DATABASE_URL (postgresql://...).')
    if not os.path.exists(args.sqlite_file):
        sys.exit(f'File non trovato: {args.sqlite_file}')

    import migrations
    from db import connect, fix_sequences, init_db
    migrations.migrate(args.sqlite_file, log=print)
    init_db(log=print)

    src = sqlite3.connect(args.sqlite_file)
    dst = connect(None)
    raw = dst.raw
    try:
        if raw.execute('SELECT COUNT(*) FROM users').fetchone()[0]:
            if not args.replace:
                sys.exit('PostgreSQL contiene già degli utenti: usa --replace per svuotarlo e ricopiare tutto.')
            raw.execute('TRUNCATE ' + ', '.join(TABLES) + ' RESTART IDENTITY')

        for t in TABLES:
            if not src.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (t,)).fetchone():
                continue
            src_cols = [r[1] for r in src.execute(f'PRAGMA table_info({t})')]
            dst_cols = {r[0] for r in raw.execute('SELECT column_name FROM information_schema.columns '
                                                  'WHERE table_schema=%s AND table_name=%s', ('public', t))}
            cols = [c for c in src_cols if c in dst_cols]
            rows = src.execute(f'SELECT {", ".join(cols)} FROM {t}').fetchall()
            with raw.cursor() as cur, cur.copy(f'COPY {t} ({", ".join(cols)}) FROM STDIN') as cp:
                for r in rows:
                    cp.write_row(r)
            print(f'{t:24} {len(rows):>7} righe')
        fix_sequences(dst)
        raw.commit()

        # Verifica: stesse righe e stessi totali.
        bad = []
        for t in TABLES:
            if not src.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (t,)).fetchone():
                continue
            a = src.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0]
            b = raw.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0]
            if a != b:
                bad.append(f'{t}: {a} righe in SQLite, {b} in PostgreSQL')
            if t in SUMS:
                sa = src.execute(f'SELECT ROUND(COALESCE(SUM({SUMS[t]}), 0), 2) FROM {t}').fetchone()[0]
                sb = raw.execute(f'SELECT ROUND(COALESCE(SUM({SUMS[t]}), 0)::numeric, 2) FROM {t}').fetchone()[0]
                if abs(float(sa) - float(sb)) > 0.005:
                    bad.append(f'{t}: totale {sa} in SQLite, {sb} in PostgreSQL')
        if bad:
            sys.exit('Copia NON coerente:\n  ' + '\n  '.join(bad))
        print('Copia completata: righe e totali coincidono.')
    finally:
        dst.close()
        src.close()


if __name__ == '__main__':
    main()
