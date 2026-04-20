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
        conn.execute('''
            CREATE TABLE IF NOT EXISTS recurring_expenses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL DEFAULT 1,
                day_of_month INTEGER NOT NULL,
                euro REAL NOT NULL,
                type TEXT NOT NULL,
                category TEXT NOT NULL,
                description TEXT DEFAULT '',
                auto_insert INTEGER NOT NULL DEFAULT 0,
                active INTEGER NOT NULL DEFAULT 1
            )
        ''')
        conn.commit()


_init_db()
