import sqlite3
from contextlib import contextmanager
from config import Config


@contextmanager
def finance_db():
    """Context manager per la connessione a finance.db. Chiude sempre la connessione."""
    conn = sqlite3.connect(Config.FINANCE_DB)
    try:
        yield conn
    finally:
        conn.close()


def _init_db():
    """Porta lo schema alla versione più recente (vedi migrations.py)."""
    from migrations import migrate
    migrate(Config.FINANCE_DB)


_init_db()
