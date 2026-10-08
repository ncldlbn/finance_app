"""Migrazioni versionate dello schema SQLite.

La versione corrente sta nel database stesso (`PRAGMA user_version`). Ogni migrazione ha un numero
progressivo, gira UNA volta, dentro una transazione (o riesce tutta o non cambia nulla) e deve essere
idempotente quando possibile, perché i database esistenti partono da versione 0.

Come aggiungerne una: scrivere una funzione `m_NNN_descrizione(conn)` e metterla in coda a MIGRATIONS
con il numero successivo. MAI modificare né rimuovere una migrazione già pubblicata.

Prima di applicare migrazioni a un database che contiene già dati, se ne salva una copia accanto al file
(`<nome>.pre-v<versione>`): si può tornare indietro rimettendo quel file al suo posto.
"""
import os
import sqlite3
from datetime import datetime


def _run(conn, script):
    """Esegue più istruzioni SQL una per una. NON usare `executescript`: chiude da solo la transazione
    in corso e farebbe perdere l'atomicità della migrazione."""
    for stmt in script.split(';'):
        if stmt.strip():
            conn.execute(stmt)


def m_001_baseline(conn):
    """Tabelle di base. IF NOT EXISTS: sui database esistenti non cambia nulla."""
    _run(conn, '''
        CREATE TABLE IF NOT EXISTS category (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL DEFAULT 1,
            type TEXT CHECK(type IN ('essential','extra')) NOT NULL,
            category TEXT NOT NULL, budget REAL DEFAULT 0,
            UNIQUE(user_id, type, category)
        );
        CREATE TABLE IF NOT EXISTS incomes (
            id INTEGER PRIMARY KEY, date TEXT NOT NULL, user_id INTEGER NOT NULL,
            euro REAL NOT NULL, description TEXT
        );
        CREATE TABLE IF NOT EXISTS expenses (
            id INTEGER PRIMARY KEY, date TEXT NOT NULL, user_id INTEGER NOT NULL,
            euro REAL NOT NULL, description TEXT, category TEXT, type TEXT
        );
        CREATE TABLE IF NOT EXISTS patrimonio (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            anno INTEGER NOT NULL, mese INTEGER NOT NULL,
            bcc REAL DEFAULT 0, bbva REAL DEFAULT 0, directa REAL DEFAULT 0,
            deposito REAL DEFAULT 0, obblig REAL DEFAULT 0, etf_etc REAL DEFAULT 0,
            debito REAL DEFAULT 0, credito REAL DEFAULT 0, cauzioni REAL DEFAULT 0,
            tfr REAL DEFAULT 0, fon_te REAL DEFAULT 0,
            UNIQUE(anno, mese)
        );
        CREATE TABLE IF NOT EXISTS recurring_expenses (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL DEFAULT 1,
            day_of_month INTEGER NOT NULL, euro REAL NOT NULL, type TEXT NOT NULL,
            category TEXT NOT NULL, description TEXT DEFAULT '',
            auto_insert INTEGER NOT NULL DEFAULT 0, active INTEGER NOT NULL DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS planned_expenses (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL DEFAULT 1,
            month TEXT NOT NULL, euro REAL NOT NULL, description TEXT NOT NULL DEFAULT '',
            category TEXT NOT NULL DEFAULT '', due_date TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS login_attempts (ip TEXT NOT NULL, ts REAL NOT NULL);
    ''')


def m_002_budgets_per_year(conn):
    """Budget per anno (tabella `budgets`). I vecchi budget globali in `settings` diventano quelli
    dell'anno corrente (una sola volta: solo se la tabella è ancora vuota)."""
    conn.execute('''
        CREATE TABLE IF NOT EXISTS budgets (
            year INTEGER NOT NULL, kind TEXT NOT NULL,
            value REAL NOT NULL DEFAULT 0, period TEXT NOT NULL DEFAULT 'annuale',
            PRIMARY KEY (year, kind)
        )''')
    # Il budget extra annuale era salvato sotto 'extra_budget_total' (sempre annuale).
    conn.execute("INSERT OR IGNORE INTO settings(key, value) "
                 "SELECT 'extra_budget_value', value FROM settings WHERE key='extra_budget_total'")
    conn.execute("INSERT OR IGNORE INTO settings(key, value) "
                 "SELECT 'extra_budget_period', 'annuale' FROM settings WHERE key='extra_budget_total'")
    if conn.execute("SELECT COUNT(*) FROM budgets").fetchone()[0] == 0:
        for kind, vk, pk in (('essential', 'essential_budget_value', 'essential_budget_period'),
                             ('extra', 'extra_budget_value', 'extra_budget_period'),
                             ('savings', 'savings_goal_value', 'savings_goal_period')):
            row = conn.execute("SELECT value FROM settings WHERE key=?", (vk,)).fetchone()
            if row:
                per = conn.execute("SELECT value FROM settings WHERE key=?", (pk,)).fetchone()
                conn.execute("INSERT INTO budgets (year, kind, value, period) VALUES (?,?,?,?)",
                             (datetime.now().year, kind, float(row[0]), per[0] if per else 'annuale'))


def m_003_indexes(conn):
    """Indici per le interrogazioni più frequenti (per data e per categoria, senza maiuscole)."""
    _run(conn, '''
        CREATE INDEX IF NOT EXISTS idx_expenses_date     ON expenses(date);
        CREATE INDEX IF NOT EXISTS idx_expenses_category ON expenses(category COLLATE NOCASE);
        CREATE INDEX IF NOT EXISTS idx_incomes_date      ON incomes(date);
        CREATE INDEX IF NOT EXISTS idx_planned_month     ON planned_expenses(month);
    ''')


def _columns(conn, table):
    return [r[1] for r in conn.execute(f'PRAGMA table_info({table})')]


def m_004_multiutente(conn):
    """Multiutente vero: tabella `users` e `user_id` anche in `patrimonio` e `budgets` (che erano globali).
    I dati esistenti restano dell'utente 1 (il proprietario). Le altre tabelle avevano già `user_id`."""
    if 'users' not in {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}:
        _run(conn, '''
            CREATE TABLE users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE COLLATE NOCASE,
                password_hash TEXT NOT NULL,
                is_demo INTEGER NOT NULL DEFAULT 0,
                data_date TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )''')
    else:                                           # tabella `users` già presente nel vecchio database
        cols = _columns(conn, 'users')
        if 'is_demo' not in cols:
            conn.execute('ALTER TABLE users ADD COLUMN is_demo INTEGER NOT NULL DEFAULT 0')
        if 'data_date' not in cols:
            conn.execute("ALTER TABLE users ADD COLUMN data_date TEXT NOT NULL DEFAULT ''")

    if 'user_id' not in _columns(conn, 'patrimonio'):
        _run(conn, '''
            CREATE TABLE patrimonio_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL DEFAULT 1,
                anno INTEGER NOT NULL, mese INTEGER NOT NULL,
                bcc REAL DEFAULT 0, bbva REAL DEFAULT 0, directa REAL DEFAULT 0,
                deposito REAL DEFAULT 0, obblig REAL DEFAULT 0, etf_etc REAL DEFAULT 0,
                debito REAL DEFAULT 0, credito REAL DEFAULT 0, cauzioni REAL DEFAULT 0,
                tfr REAL DEFAULT 0, fon_te REAL DEFAULT 0,
                UNIQUE(user_id, anno, mese)
            );
            INSERT INTO patrimonio_new (id, user_id, anno, mese, bcc, bbva, directa, deposito, obblig, etf_etc,
                                        debito, credito, cauzioni, tfr, fon_te)
                SELECT id, 1, anno, mese, bcc, bbva, directa, deposito, obblig, etf_etc,
                       debito, credito, cauzioni, tfr, fon_te FROM patrimonio;
            DROP TABLE patrimonio;
            ALTER TABLE patrimonio_new RENAME TO patrimonio''')

    if 'user_id' not in _columns(conn, 'budgets'):
        _run(conn, '''
            CREATE TABLE budgets_new (
                user_id INTEGER NOT NULL DEFAULT 1,
                year INTEGER NOT NULL, kind TEXT NOT NULL,
                value REAL NOT NULL DEFAULT 0, period TEXT NOT NULL DEFAULT 'annuale',
                PRIMARY KEY (user_id, year, kind)
            );
            INSERT INTO budgets_new (user_id, year, kind, value, period)
                SELECT 1, year, kind, value, period FROM budgets;
            DROP TABLE budgets;
            ALTER TABLE budgets_new RENAME TO budgets''')

    _run(conn, '''
        CREATE INDEX IF NOT EXISTS idx_expenses_user_date ON expenses(user_id, date);
        CREATE INDEX IF NOT EXISTS idx_incomes_user_date  ON incomes(user_id, date);
        CREATE INDEX IF NOT EXISTS idx_category_user      ON category(user_id)''')


MIGRATIONS = [
    (1, 'baseline', m_001_baseline),
    (2, 'budgets_per_year', m_002_budgets_per_year),
    (3, 'indexes', m_003_indexes),
    (4, 'multiutente', m_004_multiutente),
]
LATEST = MIGRATIONS[-1][0]


def current_version(conn):
    return conn.execute('PRAGMA user_version').fetchone()[0]


def _has_data(conn):
    return conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='expenses'").fetchone()[0] > 0


def _backup_file(path, version):
    """Copia coerente del database prima di migrarlo (API di backup di SQLite). Una sola per versione."""
    dest = f'{path}.pre-v{version}'
    if os.path.exists(dest):
        return None
    src, dst = sqlite3.connect(path), sqlite3.connect(dest)
    try:
        src.backup(dst)
    finally:
        dst.close(); src.close()
    return dest


def migrate(path, log=print):
    """Porta il database alla versione più recente. Ritorna l'elenco delle migrazioni applicate."""
    parent = os.path.dirname(os.path.abspath(path))
    os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30, isolation_level=None)   # transazioni gestite a mano
    applied = []
    try:
        version = current_version(conn)
        pending = [m for m in MIGRATIONS if m[0] > version]
        if pending and _has_data(conn):
            saved = _backup_file(path, version)
            if saved:
                log(f'Copia di sicurezza prima di migrare: {saved}')
        for number, name, fn in pending:
            conn.execute('BEGIN IMMEDIATE')
            try:
                # Un altro processo può aver migrato mentre aspettavamo il blocco.
                if current_version(conn) >= number:
                    conn.execute('ROLLBACK'); continue
                fn(conn)
                conn.execute(f'PRAGMA user_version = {int(number)}')
                conn.execute('COMMIT')
            except Exception:
                conn.execute('ROLLBACK')
                raise
            applied.append(f'{number:03d}_{name}')
            log(f'Migrazione applicata: {number:03d}_{name}')
    finally:
        conn.close()
    return applied
