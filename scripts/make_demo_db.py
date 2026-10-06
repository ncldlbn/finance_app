"""Create a SQLite database filled with synthetic data (no real personal data).

Used to run the app for demos and to take the README screenshots:

    python scripts/make_demo_db.py demo.db
    FINANCE_DB=demo.db python app.py

The data is deterministic (fixed random seed) and relative to today's date, so
the current year always has content.
"""
import os
import random
import sqlite3
import sys
from datetime import date, timedelta

SCHEMA = """
CREATE TABLE category (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL DEFAULT 1,
    type TEXT CHECK(type IN ('essential','extra')) NOT NULL,
    category TEXT NOT NULL, budget REAL DEFAULT 0,
    UNIQUE(user_id, type, category)
);
CREATE TABLE incomes (
    id INTEGER PRIMARY KEY, date TEXT NOT NULL, user_id INTEGER NOT NULL,
    euro REAL NOT NULL, description TEXT
);
CREATE TABLE expenses (
    id INTEGER PRIMARY KEY, date TEXT NOT NULL, user_id INTEGER NOT NULL,
    euro REAL NOT NULL, description TEXT, category TEXT, type TEXT
);
CREATE TABLE patrimonio (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    anno INTEGER NOT NULL, mese INTEGER NOT NULL,
    bcc REAL DEFAULT 0, bbva REAL DEFAULT 0, directa REAL DEFAULT 0,
    deposito REAL DEFAULT 0, obblig REAL DEFAULT 0, etf_etc REAL DEFAULT 0,
    debito REAL DEFAULT 0, credito REAL DEFAULT 0, cauzioni REAL DEFAULT 0,
    tfr REAL DEFAULT 0, fon_te REAL DEFAULT 0,
    UNIQUE(anno, mese)
);
CREATE TABLE recurring_expenses (
    id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL DEFAULT 1,
    day_of_month INTEGER NOT NULL, euro REAL NOT NULL, type TEXT NOT NULL,
    category TEXT NOT NULL, description TEXT DEFAULT '',
    auto_insert INTEGER NOT NULL DEFAULT 0, active INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE planned_expenses (
    id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL DEFAULT 1,
    month TEXT NOT NULL, euro REAL NOT NULL, description TEXT NOT NULL DEFAULT '',
    category TEXT NOT NULL DEFAULT '', due_date TEXT NOT NULL DEFAULT ''
);
CREATE TABLE transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT NOT NULL, ticker TEXT NOT NULL,
    quantity REAL NOT NULL, price REAL NOT NULL
);
"""

ESSENTIAL = ['Casa', 'Cibo', 'Bollette', 'Trasporti', 'Salute', 'Assicurazioni', 'Telefono']
EXTRA = ['Ristoranti', 'Hobby', 'Viaggi', 'Abbonamenti', 'Abbigliamento', 'Regali']


def add_months(d, n):
    idx = d.year * 12 + d.month - 1 + n
    return date(idx // 12, idx % 12 + 1, 1)


def main(path):
    if os.path.exists(path):
        os.remove(path)
    rnd = random.Random(42)
    today = date.today()
    start = date(today.year - 3, 1, 1)
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)

    for c in ESSENTIAL:
        conn.execute("INSERT INTO category (type, category) VALUES ('essential', ?)", (c,))
    for c in EXTRA:
        conn.execute("INSERT INTO category (type, category) VALUES ('extra', ?)", (c,))

    def expense(d, euro, cat, desc):
        t = 'essential' if cat in ESSENTIAL else 'extra'
        conn.execute("INSERT INTO expenses (date, user_id, euro, description, category, type) "
                     "VALUES (?,1,?,?,?,?)", (d.isoformat(), round(euro, 2), desc, cat, t))

    def income(d, euro, desc):
        conn.execute("INSERT INTO incomes (date, user_id, euro, description) VALUES (?,1,?,?)",
                     (d.isoformat(), round(euro, 2), desc))

    month = start
    while month <= today:
        years_in = (month.year - start.year) + (month.month - 1) / 12
        infl = 1 + 0.03 * years_in                      # gentle inflation
        last_day = (add_months(month, 1) - timedelta(days=1)).day

        def day(n):
            return month.replace(day=min(n, last_day))

        def ok(d):                                       # nothing in the future
            return d <= today

        if ok(day(1)):
            expense(day(1), 650, 'Casa', 'Affitto')
        if ok(day(5)):
            expense(day(5), 25, 'Telefono', 'Piano mobile')
        if ok(day(12)):
            expense(day(12), 40, 'Assicurazioni', 'Assicurazione casa')
        for _ in range(rnd.randint(9, 13)):              # groceries
            d = day(rnd.randint(1, 28))
            if ok(d):
                expense(d, rnd.uniform(12, 48) * infl, 'Cibo',
                        rnd.choice(['Supermercato', 'Mercato', 'Panificio', 'Alimentari']))
        winter = month.month in (11, 12, 1, 2)
        if ok(day(18)):
            expense(day(18), rnd.uniform(70, 120) * (1.35 if winter else 0.85) * infl, 'Bollette', 'Luce e gas')
        if ok(day(20)):
            expense(day(20), rnd.uniform(28, 38), 'Bollette', 'Internet')
        for _ in range(rnd.randint(2, 4)):
            d = day(rnd.randint(1, 28))
            if ok(d):
                expense(d, rnd.uniform(15, 55) * infl, 'Trasporti', rnd.choice(['Carburante', 'Abbonamento bus', 'Parcheggio']))
        if rnd.random() < 0.45:
            d = day(rnd.randint(1, 28))
            if ok(d):
                expense(d, rnd.uniform(20, 95), 'Salute', rnd.choice(['Farmacia', 'Visita', 'Analisi']))
        if month.month == 11 and ok(day(15)):
            expense(day(15), 380 * infl, 'Assicurazioni', 'Assicurazione auto')
        # Extra
        for _ in range(rnd.randint(3, 6)):
            d = day(rnd.randint(1, 28))
            if ok(d):
                expense(d, rnd.uniform(18, 48), 'Ristoranti', rnd.choice(['Cena fuori', 'Pizzeria', 'Aperitivo', 'Pranzo']))
        if rnd.random() < 0.7:
            d = day(rnd.randint(1, 28))
            if ok(d):
                expense(d, rnd.uniform(15, 90), 'Hobby', rnd.choice(['Libri', 'Materiale sport', 'Cinema', 'Concerto']))
        if ok(day(10)):
            expense(day(10), 35, 'Abbonamenti', 'Streaming e musica')
        if month.month in (3, 4, 9, 10, 12) and rnd.random() < 0.8:
            d = day(rnd.randint(3, 25))
            if ok(d):
                expense(d, rnd.uniform(40, 150), 'Abbigliamento', 'Negozio abbigliamento')
        if month.month in (7, 8) and ok(day(14)):
            expense(day(14), rnd.uniform(500, 900), 'Viaggi', 'Vacanza estiva')
        if month.month == 12:
            if ok(day(20)):
                expense(day(20), rnd.uniform(180, 320), 'Regali', 'Regali di Natale')
            if ok(day(23)):
                expense(day(23), rnd.uniform(150, 350), 'Viaggi', 'Weekend fuori porta')
        # Income
        salary = 2300 * (1 + 0.03 * int(years_in))
        if ok(day(1)):
            income(day(1), salary, 'Stipendio')
        if month.month == 12 and ok(day(15)):
            income(day(15), salary, 'Tredicesima')
        if rnd.random() < 0.18 and ok(day(9)):
            income(day(9), rnd.uniform(250, 650), 'Lavoro occasionale')
        month = add_months(month, 1)

    # Net worth: one row per month, growing with noise
    state = dict(bcc=2800, bbva=1500, directa=3500, deposito=9000, obblig=4000, etf_etc=5000, tfr=6500, fon_te=2200)
    month = start
    while month <= today:
        for k, inc in dict(bcc=40, bbva=20, directa=60, deposito=70, obblig=35, etf_etc=150, tfr=170, fon_te=95).items():
            state[k] += inc + rnd.uniform(-45, 70) * (3 if k == 'etf_etc' else 1)
        conn.execute("INSERT INTO patrimonio (anno, mese, bcc, bbva, directa, deposito, obblig, etf_etc, tfr, fon_te) "
                     "VALUES (?,?,?,?,?,?,?,?,?,?)",
                     (month.year, month.month) + tuple(round(state[k], 2) for k in
                      ('bcc', 'bbva', 'directa', 'deposito', 'obblig', 'etf_etc', 'tfr', 'fon_te')))
        month = add_months(month, 1)

    # Settings, recurring rules, planned expenses
    for k, v in [('savings_goal_value', '9000'), ('savings_goal_period', 'annuale'),
                 ('extra_budget_value', '4500'), ('extra_budget_period', 'annuale')]:
        conn.execute("INSERT INTO settings (key, value) VALUES (?,?)", (k, v))
    for day_, euro, typ, cat, desc, auto in [(1, 650, 'essential', 'Casa', 'Affitto', 1),
                                              (5, 25, 'essential', 'Telefono', 'Piano mobile', 1),
                                              (10, 35, 'extra', 'Abbonamenti', 'Streaming e musica', 0)]:
        conn.execute("INSERT INTO recurring_expenses (day_of_month, euro, type, category, description, auto_insert) "
                     "VALUES (?,?,?,?,?,?)", (day_, euro, typ, cat, desc, auto))
    nxt = lambda n: add_months(today.replace(day=1), n)
    for n, euro, desc, cat, due in [(0, 120, 'Dentista', 'Salute', 20), (1, 180, 'Revisione auto', 'Trasporti', 12),
                                    (1, 60, 'Concerto', 'Hobby', 0), (2, 420, 'Assicurazione auto', 'Assicurazioni', 15),
                                    (2, 300, 'Regali di Natale', 'Regali', 0), (3, 900, 'Weekend sulla neve', 'Viaggi', 0),
                                    (3, 85, 'Abbonamento palestra', '', 0), (5, 1200, 'Vacanza estiva', 'Viaggi', 0)]:
        m = nxt(n)
        conn.execute("INSERT INTO planned_expenses (month, euro, description, category, due_date) VALUES (?,?,?,?,?)",
                     (f"{m.year}-{m.month:02d}", euro, desc, cat, m.replace(day=due).isoformat() if due else ''))
    conn.commit()
    conn.close()
    print(f"Demo database written to {path}")


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else 'demo.db')
