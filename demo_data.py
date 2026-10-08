"""Dati fittizi per l'account demo (e per il database di esempio degli screenshot).

Sono generati in modo deterministico (seme fisso) e RELATIVI A OGGI: l'anno corrente ha sempre contenuto.
Nessun dato reale entra mai qui. Le funzioni lavorano su una connessione e un `user_id` espliciti.
"""
import random
from datetime import date, timedelta

ESSENTIAL = ['Casa', 'Cibo', 'Bollette', 'Trasporti', 'Salute', 'Assicurazioni', 'Telefono']
EXTRA = ['Ristoranti', 'Hobby', 'Viaggi', 'Abbonamenti', 'Abbigliamento', 'Regali']

PERSONAL_TABLES = ('expenses', 'incomes', 'patrimonio', 'recurring_expenses', 'planned_expenses', 'budgets', 'category')


def add_months(d, n):
    idx = d.year * 12 + d.month - 1 + n
    return date(idx // 12, idx % 12 + 1, 1)


def seed_categories(conn, uid):
    """Categorie di partenza di un utente (se non ne ha ancora)."""
    if conn.execute('SELECT COUNT(*) FROM category WHERE user_id=?', (uid,)).fetchone()[0]:
        return
    for typ, names in (('essential', ESSENTIAL), ('extra', EXTRA)):
        for c in names:
            conn.execute('INSERT INTO category (user_id, type, category, budget) VALUES (?,?,?,0)', (uid, typ, c))


def clear_user_data(conn, uid):
    """Cancella TUTTI i dati personali di un utente (non l'utente)."""
    for t in PERSONAL_TABLES:
        conn.execute(f'DELETE FROM {t} WHERE user_id=?', (uid,))


def populate(conn, uid, today=None):
    """Sostituisce i dati dell'utente `uid` con un anno di dati fittizi plausibili (3 anni di storia)."""
    today = today or date.today()
    clear_user_data(conn, uid)
    seed_categories(conn, uid)
    rnd = random.Random(42)
    start = date(today.year - 3, 1, 1)

    def expense(d, euro, cat, desc):
        t = 'essential' if cat in ESSENTIAL else 'extra'
        conn.execute('INSERT INTO expenses (date, user_id, euro, description, category, type) VALUES (?,?,?,?,?,?)',
                     (d.isoformat(), uid, round(euro, 2), desc, cat, t))

    def income(d, euro, desc):
        conn.execute('INSERT INTO incomes (date, user_id, euro, description) VALUES (?,?,?,?)',
                     (d.isoformat(), uid, round(euro, 2), desc))

    month = start
    while month <= today:
        years_in = (month.year - start.year) + (month.month - 1) / 12
        infl = 1 + 0.03 * years_in                      # inflazione lieve
        last_day = (add_months(month, 1) - timedelta(days=1)).day

        def day(n, month=month, last_day=last_day):
            return month.replace(day=min(n, last_day))

        def ok(d):                                       # niente nel futuro
            return d <= today

        if ok(day(1)):
            expense(day(1), 650, 'Casa', 'Affitto')
        if ok(day(5)):
            expense(day(5), 25, 'Telefono', 'Piano mobile')
        if ok(day(12)):
            expense(day(12), 40, 'Assicurazioni', 'Assicurazione casa')
        for _ in range(rnd.randint(9, 13)):              # spesa alimentare
            d = day(rnd.randint(1, 28))
            if ok(d):
                expense(d, rnd.uniform(12, 48) * infl, 'Cibo', rnd.choice(['Supermercato', 'Mercato', 'Panificio', 'Alimentari']))
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
        for _ in range(rnd.randint(3, 6)):               # extra
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
        salary = 2300 * (1 + 0.03 * int(years_in))
        if ok(day(1)):
            income(day(1), salary, 'Stipendio')
        if month.month == 12 and ok(day(15)):
            income(day(15), salary, 'Tredicesima')
        if rnd.random() < 0.18 and ok(day(9)):
            income(day(9), rnd.uniform(250, 650), 'Lavoro occasionale')
        month = add_months(month, 1)

    # Patrimonio: una riga al mese, in crescita con un po' di rumore
    state = dict(bcc=2800, bbva=1500, directa=3500, deposito=9000, obblig=4000, etf_etc=5000, tfr=6500, fon_te=2200)
    fields = ('bcc', 'bbva', 'directa', 'deposito', 'obblig', 'etf_etc', 'tfr', 'fon_te')
    month = start
    while month <= today:
        for k, inc in dict(bcc=40, bbva=20, directa=60, deposito=70, obblig=35, etf_etc=150, tfr=170, fon_te=95).items():
            state[k] += inc + rnd.uniform(-45, 70) * (3 if k == 'etf_etc' else 1)
        conn.execute('INSERT INTO patrimonio (user_id, anno, mese, ' + ', '.join(fields) + ') VALUES (?,?,?,' + ','.join('?' * 8) + ')',
                     (uid, month.year, month.month) + tuple(round(state[k], 2) for k in fields))
        month = add_months(month, 1)

    # Budget per anno (cambiano nel tempo), ricorrenti e spese previste
    for yr, ess, ext, sav in [(today.year - 2, 1300, 4000, 7000), (today.year - 1, 1380, 4200, 8000), (today.year, 1450, 4500, 9000)]:
        for kind, value, period in (('essential', ess, 'mensile'), ('extra', ext, 'annuale'), ('savings', sav, 'annuale')):
            conn.execute('INSERT INTO budgets (user_id, year, kind, value, period) VALUES (?,?,?,?,?)', (uid, yr, kind, value, period))
    for day_, euro, typ, cat, desc, auto in [(1, 650, 'essential', 'Casa', 'Affitto', 1), (5, 25, 'essential', 'Telefono', 'Piano mobile', 1),
                                             (10, 35, 'extra', 'Abbonamenti', 'Streaming e musica', 0)]:
        conn.execute('INSERT INTO recurring_expenses (user_id, day_of_month, euro, type, category, description, auto_insert) '
                     'VALUES (?,?,?,?,?,?,?)', (uid, day_, euro, typ, cat, desc, auto))
    for n, euro, desc, cat, due in [(0, 120, 'Dentista', 'Salute', 20), (1, 180, 'Revisione auto', 'Trasporti', 12),
                                    (1, 60, 'Concerto', 'Hobby', 0), (2, 420, 'Assicurazione auto', 'Assicurazioni', 15),
                                    (2, 300, 'Regali di Natale', 'Regali', 0), (3, 900, 'Weekend sulla neve', 'Viaggi', 0),
                                    (3, 85, 'Abbonamento palestra', '', 0), (5, 1200, 'Vacanza estiva', 'Viaggi', 0)]:
        m = add_months(today.replace(day=1), n)
        conn.execute('INSERT INTO planned_expenses (user_id, month, euro, description, category, due_date) VALUES (?,?,?,?,?,?)',
                     (uid, f'{m.year}-{m.month:02d}', euro, desc, cat, m.replace(day=due).isoformat() if due else ''))
