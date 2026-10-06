"""Pagina Monitor: heatmap mesi × categorie con totali laterali."""
from flask import Blueprint, render_template
import json, sys, os
from datetime import datetime
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from db import finance_db
from helpers import q, categories, all_years as _all_years

monitor_bp = Blueprint('monitor', __name__)


def _heatmap_data(conn, today, all_years):
    """Tabella mesi × categorie. Si caricano tutti gli anni con dati, dal mese
    corrente a ritroso (i mesi futuri non esistono); il filtro sul periodo
    (anno in corso / 3 anni / 10 anni / totale) è client-side.
    Colonne nello stesso ordine della lista di Bilancio (prima le
    necessità, poi le extra). I dati vanno al client in forma grezza (importi
    per mese/categoria, entrate per mese, elenco spese): gli switch
    assoluto/% e mensile/annuale e il popup di dettaglio sono tutti
    client-side, senza giri al server."""
    cats_master = categories(conn)
    cols = [{'name': c, 'type': t}
            for group in ('essential', 'extra') for c, t in cats_master if t == group]
    canon_of = {c['name'].lower(): c['name'] for c in cols}
    first_year = min(int(y) for y in all_years)

    rows = q(conn, """
        SELECT strftime('%Y-%m', e.date), e.category, e.date, e.euro, COALESCE(e.description, '')
        FROM expenses e JOIN category c ON e.category=c.category COLLATE NOCASE
        WHERE e.user_id=1 AND strftime('%Y', e.date) >= ?
        ORDER BY e.date DESC""", (str(first_year),))
    amt, expenses = defaultdict(lambda: defaultdict(float)), []
    for ym, cat, date, euro, desc in rows:
        # La JOIN è case-insensitive: riallinea al nome canonico della categoria.
        cat = canon_of.get(cat.lower(), cat)
        amt[ym][cat] += euro
        expenses.append([ym, cat, date, round(euro, 2), desc])

    inc = {ym: round(v, 2) for ym, v in q(conn, """
        SELECT strftime('%Y-%m', date), SUM(euro) FROM incomes
        WHERE user_id=1 AND strftime('%Y', date) >= ? GROUP BY 1""", (str(first_year),))}

    months = []
    y, m = today.year, today.month
    while y >= first_year:
        months.append(f"{y}-{m:02d}")
        m -= 1
        if m == 0:
            y, m = y - 1, 12

    return {'heat_json': json.dumps({
        'cols': cols, 'months': months, 'current_year': today.year,
        'amt': {ym: {c: round(v, 2) for c, v in d.items()} for ym, d in amt.items()},
        'inc': inc, 'exp': expenses,
        'rgb': {'essential': '44,89,162', 'extra': '132,86,193',
                'income': '41,147,136', 'saving': '194,145,63', 'deficit': '196,80,80'},
    })}


@monitor_bp.route('/monitor')
def index():
    today = datetime.today()
    with finance_db() as conn:
        all_years = _all_years(conn)
        if not all_years:
            return render_template('monitor.html', empty=True)
        ctx = _heatmap_data(conn, today, all_years)
    return render_template('monitor.html', empty=False, **ctx)
