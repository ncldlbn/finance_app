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
    """Crea la tabella transactions in finance.db se non esiste."""
    with finance_db() as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                ticker TEXT NOT NULL,
                quantity REAL NOT NULL,
                price REAL NOT NULL
            )
        ''')
        conn.commit()


_init_db()
