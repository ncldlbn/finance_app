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

BACKEND = 'postgres' if (Config.DATABASE_URL or Config.DATABASE_OWNER_URL) else 'sqlite'


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
    commit, rollback, close, `with conn:` = commit o rollback senza chiudere). `close()` la restituisce al pool."""

    def __init__(self, raw, release):
        self.raw = raw
        self._release = release

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
        if self.raw is not None:
            self._release(self.raw)
            self.raw = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type is None:
            self.raw.commit()
        else:
            self.raw.rollback()
        return False


_pool = None
_pool_pid = None
_loaders_ready = False


def _pg_setup_loaders():
    """Le date arrivano all'app come testo AAAA-MM-GG e gli importi (numeric, esatti nel database) come float:
    così il codice resta uguale a quello per SQLite."""
    global _loaders_ready
    if _loaders_ready:
        return
    import psycopg
    from psycopg.types.numeric import FloatLoader
    from psycopg.types.string import TextLoader
    psycopg.adapters.register_loader('numeric', FloatLoader)
    psycopg.adapters.register_loader('date', TextLoader)
    _loaders_ready = True


def _pg_pool():
    """Un pool di connessioni per processo (creato alla prima richiesta, dopo il fork dei worker di gunicorn).
    Ogni connessione ha un limite di tempo per le query (DB_STATEMENT_TIMEOUT_MS) e un nome riconoscibile."""
    global _pool, _pool_pid
    if _pool is None or _pool_pid != os.getpid():
        from psycopg_pool import ConnectionPool
        _pg_setup_loaders()
        timeout = int(os.environ.get('DB_STATEMENT_TIMEOUT_MS', '15000'))
        _pool = ConnectionPool(Config.DATABASE_URL, min_size=1, max_size=int(os.environ.get('DB_POOL_MAX', '10')),
                               kwargs={'options': f'-c statement_timeout={timeout} -c application_name=bilancio'},
                               open=True, name='bilancio')
        _pool_pid = os.getpid()
    return _pool


def _pg_release(raw):
    """Restituisce la connessione al pool pulita: transazione annullata e nessun utente associato."""
    try:
        raw.rollback()
        raw.execute("SELECT set_config('app.user_id', '', false)")
        raw.commit()
    finally:
        _pg_pool().putconn(raw)


def _pg_connect(uid):
    raw = _pg_pool().getconn()
    # current_uid() (e quindi la Row-Level Security) legge questa impostazione; vuota = nessun utente.
    raw.execute("SELECT set_config('app.user_id', %s, false)", ('' if uid is None else str(uid),))
    raw.commit()
    return PGConnection(raw, _pg_release)


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
    """Schema aggiornato prima di tutto.
    SQLite: le migrazioni versionate (crea il file se manca).
    PostgreSQL: con DATABASE_OWNER_URL applica le migrazioni (migrations_pg.py) e aggiorna l'utente dell'app;
    senza, controlla soltanto che lo schema sia aggiornato (in docker compose lo aggiorna il servizio «migrate»)."""
    import migrations
    if BACKEND == 'sqlite':
        return migrations.migrate(Config.FINANCE_DB, **({'log': log} if log else {}))
    import migrations_pg
    if migrations_pg.SQLITE_LEVEL != migrations.LATEST:
        raise RuntimeError(f'Lo schema PostgreSQL arriva alla migrazione SQLite {migrations_pg.SQLITE_LEVEL}, il codice '
                           f'alla {migrations.LATEST}: va scritta la migrazione PostgreSQL corrispondente (migrations_pg.py).')
    if Config.DATABASE_OWNER_URL:
        migrations_pg.migrate(Config.DATABASE_OWNER_URL, log=log,
                              app_role=os.environ.get('APP_DB_USER', 'bilancio_app'),
                              app_password=os.environ.get('APP_DB_PASSWORD', ''))
    if not Config.DATABASE_URL:
        return
    import psycopg
    with psycopg.connect(Config.DATABASE_URL) as raw:
        ok = raw.execute("SELECT to_regclass('public.schema_migrations')").fetchone()[0] is not None
        version = raw.execute('SELECT MAX(version) FROM schema_migrations').fetchone()[0] if ok else None
        if version != migrations_pg.LATEST:
            raise RuntimeError(f'Schema PostgreSQL alla versione {version}, il codice si aspetta la {migrations_pg.LATEST}: '
                               'applica le migrazioni (docker compose run --rm migrate, vedi README).')
        unsafe = raw.execute('SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname = current_user').fetchone()[0]
        if unsafe and log:
            log('Attenzione: DATABASE_URL usa un utente che scavalca la Row-Level Security; in produzione usa '
                "l'utente dell'app (APP_DB_USER).")
