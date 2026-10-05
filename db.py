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
        conn.execute('''
            CREATE TABLE IF NOT EXISTS settings (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        ''')
        conn.execute('''
            CREATE TABLE IF NOT EXISTS planned_expenses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL DEFAULT 1,
                month TEXT NOT NULL,
                euro REAL NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                category TEXT NOT NULL DEFAULT '',
                due_date TEXT NOT NULL DEFAULT ''
            )
        ''')
        # Migrazione: il budget extra annuale era salvato sotto 'extra_budget_total'
        # (sempre annuale); ora vive in extra_budget_value + extra_budget_period.
        conn.execute("""
            INSERT OR IGNORE INTO settings(key, value)
            SELECT 'extra_budget_value', value FROM settings WHERE key='extra_budget_total'
        """)
        conn.execute("""
            INSERT OR IGNORE INTO settings(key, value)
            SELECT 'extra_budget_period', 'annuale' FROM settings WHERE key='extra_budget_total'
        """)
        conn.commit()


_init_db()
