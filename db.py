import sqlite3
from config import Config


def get_finance_conn():
    return sqlite3.connect(Config.FINANCE_DB)


def get_portfolio_conn():
    return sqlite3.connect(Config.PORTFOLIO_DB)


def init_portfolio_db():
    conn = get_portfolio_conn()
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            ticker TEXT NOT NULL,
            quantity REAL NOT NULL,
            price REAL NOT NULL
        )
    ''')
    conn.commit()
    conn.close()


init_portfolio_db()
