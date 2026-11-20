"""Accesso al database: SQLite (predefinito) oppure PostgreSQL (se è impostata DATABASE_URL).

Le query dell'app sono scritte una volta sola, con i segnaposto `?` di SQLite; con PostgreSQL questo modulo li
converte in `%s` e lo schema (schema_pg.sql) ricrea le funzioni di SQLite usate dalle query: `current_uid()`,
`strftime()` e l'ordinamento `COLLATE NOCASE`.
"""
import os
import sqlite3
from contextlib import contextmanager
from functools import lru_cache

from config import Config

BACKEND = 'postgres' if Config.DATABASE_URL else 'sqlite'
SCHEMA_PG = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'schema_pg.sql')


def _request_user_id():
    """Id dell'utente della richiesta in corso (None fuori da una richiesta o se non ha fatto l'accesso)."""
    try:
        from flask import g, has_request_context
    except ImportError:                                      # pragma: no cover
        return None
    if has_request_context():
        user = getattr(g, 'user', None)
        return user['id'] if user else None
    return None


# ── PostgreSQL ───────────────────────────────────────────────────────────────

@lru_cache(maxsize=1024)
def _to_pg(sql):
    """Segnaposto `?` → `%s` fuori dalle stringhe; ogni `%` letterale diventa `%%` (psycopg li interpreta)."""
    out, quote = [], None
    for ch in sql:
        if quote:
            out.append('%%' if ch == '%' else ch)
            if ch == quote:
                quote = None
        elif ch in ("'", '"'):
            quote = ch
            out.append(ch)
        elif ch == '?':
            out.append('%s')
        elif ch == '%':
            out.append('%%')
        else:
            out.append(ch)
    return ''.join(out)


class _PGCursor:
    def __init__(self, cur):
        self._cur = cur

    def fetchone(self):
        return self._cur.fetchone()

    def fetchall(self):
        return self._cur.fetchall()

    def __iter__(self):
        return iter(self._cur)

    @property
    def rowcount(self):
        return self._cur.rowcount


class PGConnection:
    """Connessione psycopg con la stessa interfaccia minima di sqlite3 usata dall'app (execute, executemany,
    commit, rollback, close, `with conn:` = commit o rollback senza chiudere)."""

    def __init__(self, raw):
        self.raw = raw

    def execute(self, sql, params=()):
        cur = self.raw.cursor()
        cur.execute(_to_pg(sql), tuple(params))
        return _PGCursor(cur)

    def executemany(self, sql, seq):
        cur = self.raw.cursor()
        cur.executemany(_to_pg(sql), [tuple(p) for p in seq])
        return _PGCursor(cur)

    def commit(self):
        self.raw.commit()

    def rollback(self):
        self.raw.rollback()

    def close(self):
        self.raw.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type is None:
            self.raw.commit()
        else:
            self.raw.rollback()
        return False


def _pg_connect(uid):
    import psycopg
    raw = psycopg.connect(Config.DATABASE_URL)
    # current_uid() legge questa impostazione di sessione; vuota = nessun utente (le query personali falliscono).
    raw.execute("SELECT set_config('app.user_id', %s, false)", ('' if uid is None else str(uid),))
    raw.commit()
    return PGConnection(raw)


# ── Connessioni ──────────────────────────────────────────────────────────────

def connect(user_id=None):
    """Connessione aperta (da chiudere) con `current_uid()` = `user_id`."""
    if BACKEND == 'postgres':
        return _pg_connect(user_id)

    def current_uid():
        if user_id is None:
            raise sqlite3.ProgrammingError('Nessun utente associato a questa connessione')
        return user_id

    conn = sqlite3.connect(Config.FINANCE_DB)
    conn.create_function('current_uid', 0, current_uid)
    return conn


@contextmanager
def finance_db(user_id=None):
    """Connessione al database, chiusa sempre alla fine.

    Ambito utente: nelle interrogazioni SQL, `current_uid()` vale l'id dell'utente a cui appartiene la
    connessione: `user_id` esplicito, altrimenti quello della richiesta in corso. Ogni interrogazione sui
    dati personali DEVE filtrare con `user_id = current_uid()` (e ogni INSERT usare `current_uid()`).
    Se non c'è nessun utente (richiesta anonima, script senza `user_id`), `current_uid()` solleva un errore:
    l'accesso ai dati fallisce invece di mescolare quelli di utenti diversi.
    """
    conn = connect(user_id if user_id is not None else _request_user_id())
    try:
        yield conn
    finally:
        conn.close()


@contextmanager
def connect_raw():
    """Connessione senza utente (tabelle di sistema: users, login_attempts…): commit alla fine se non ci sono
    errori, rollback altrimenti, e chiusura sempre."""
    conn = connect(None)
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def fix_sequences(conn):
    """PostgreSQL: dopo inserimenti con id espliciti, riallinea i contatori degli id al massimo presente
    (altrimenti il prossimo inserimento riuserebbe un id già preso). Con SQLite non serve."""
    if BACKEND != 'postgres':
        return
    for table in ('users', 'category', 'expenses', 'incomes', 'planned_expenses', 'recurring_expenses', 'patrimonio'):
        conn.execute(f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), "
                     f"COALESCE((SELECT MAX(id) FROM {table}), 0) + 1, false)")


# ── Schema ───────────────────────────────────────────────────────────────────

def init_db(log=None):
    """Schema aggiornato prima di tutto. SQLite: le migrazioni versionate (crea il file se manca).
    PostgreSQL: lo schema completo al primo avvio (sotto un lock, così più processi non lo creano insieme)."""
    from migrations import LATEST, migrate
    if BACKEND == 'sqlite':
        return migrate(Config.FINANCE_DB, **({'log': log} if log else {}))
    import psycopg
    with psycopg.connect(Config.DATABASE_URL) as raw:
        raw.execute('SELECT pg_advisory_lock(727274)')
        try:
            if raw.execute("SELECT to_regclass('public.schema_version')").fetchone()[0] is None:
                with open(SCHEMA_PG, encoding='utf-8') as f:
                    raw.execute(f.read())
                raw.execute('CREATE TABLE schema_version (version integer NOT NULL)')
                raw.execute('INSERT INTO schema_version (version) VALUES (%s)', (LATEST,))
                raw.commit()
                if log:
                    log(f'Schema PostgreSQL creato (versione {LATEST})')
            else:
                version = raw.execute('SELECT version FROM schema_version').fetchone()[0]
                if version != LATEST:
                    raise RuntimeError(f'Schema PostgreSQL alla versione {version}, il codice si aspetta la {LATEST}: '
                                       'serve una migrazione PostgreSQL (vedi README).')
        finally:
            raw.execute('SELECT pg_advisory_unlock(727274)')
            raw.commit()
