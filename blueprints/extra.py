"""Pagina Extra: monitoraggio della spesa discrezionale.

Il budget è a scendere: si imposta un totale annuale unico, poi lo si
ripartisce tra le categorie extra restando dentro quel totale (validato,
non bloccato — la form segnala se si sfora, ma salva comunque: sono numeri
del proprietario dell'app, non regole imposte dal software).
"""
from flask import Blueprint, render_template, request, redirect, url_for, flash
import sys, os, calendar
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from db import finance_db
from helpers import q, get_setting, set_setting, MESI_IT

extra_bp = Blueprint('extra', __name__)

BUDGET_TOTAL_KEY = 'extra_budget_total'


def _ritmo_data(conn, today):
    """Un anello esterno più spesso per il totale extra, un anello più
    sottile per ciascuna categoria che ha un budget impostato (>0) — le
    categorie a budget zero non hanno un anello proprio, ma la loro spesa
    conta comunque nel totale: il residuo deve riflettere la spesa vera,
    non solo quella che si è scelto di ripartire in dettaglio.

    Una sola barretta radiale, all'angolo di oggi nell'anno, attraversa
    tutti gli anelli insieme: dove l'arco colorato di un anello supera la
    barretta, quella categoria (o il totale) sta spendendo più in fretta
    del calendario. Sempre ancorata a oggi: un ritmo ha senso solo per
    l'anno in corso."""
    budget_total_set = get_setting(conn, BUDGET_TOTAL_KEY, 0.0)
    cat_rows = q(conn, "SELECT id, category, COALESCE(budget,0) FROM category "
                       "WHERE type='extra' ORDER BY category COLLATE NOCASE")
    all_extra = [{'id': r[0], 'name': r[1], 'budget': round(r[2], 2)} for r in cat_rows]
    cat_budget_sum = round(sum(c['budget'] for c in all_extra), 2)
    budgeted = [c for c in all_extra if c['budget'] > 0]

    result = {
        'available': budget_total_set > 0,
        'budget_total_set': round(budget_total_set, 2),
        'cat_budget_sum': cat_budget_sum,
        'cat_budget_over': cat_budget_sum > budget_total_set + 0.005,
        'all_extra': all_extra, 'rings': [],
        'spent_total': 0, 'pct_total': 0,
        'residuo_totale': 0, 'residuo_mensile': 0,
        'today_angle': 0, 'today_label': '',
    }
    if not result['available']:
        return result

    # Spesa reale dell'anno per TUTTE le categorie extra, budgetizzate o no:
    # il residuo del totale deve contare tutto quello che è stato speso,
    # non solo le categorie a cui è stato assegnato un sotto-budget.
    spent_rows = q(conn, """
        SELECT e.category, SUM(e.euro) FROM expenses e
        JOIN category c ON e.category = c.category COLLATE NOCASE
        WHERE e.user_id=1 AND strftime('%Y',e.date)=? AND c.type='extra'
        GROUP BY e.category""", (str(today.year),))
    spent_map = {name: amt for name, amt in spent_rows}
    spent_total = round(sum(spent_map.values()), 2)

    rings = []
    for c in sorted(budgeted, key=lambda c: -c['budget']):
        spent = round(spent_map.get(c['name'], 0.0), 2)
        rings.append({'name': c['name'], 'budget': c['budget'], 'spent': spent,
                      'pct': round(spent / c['budget'] * 100, 1)})

    residuo_totale = round(budget_total_set - spent_total, 2)
    yr_len = 366 if calendar.isleap(today.year) else 365
    today_doy = today.timetuple().tm_yday
    # Giorni ancora da vivere quest'anno: almeno 1, per non dividere per
    # zero il 31 dicembre.
    giorni_rimanenti = max(yr_len - today_doy, 1)
    residuo_mensile = round(residuo_totale / giorni_rimanenti * 30, 2)

    result.update(
        rings=rings, spent_total=spent_total,
        pct_total=round(spent_total / budget_total_set * 100, 1) if budget_total_set else 0,
        residuo_totale=residuo_totale, residuo_mensile=residuo_mensile,
        today_angle=round(today_doy / yr_len * 360, 2),
        today_label=f"{today.day} {MESI_IT[today.month - 1].lower()}",
    )
    return result


@extra_bp.route('/extra')
def index():
    with finance_db() as conn:
        ritmo = _ritmo_data(conn, datetime.today())
    return render_template('extra.html', ritmo=ritmo)


@extra_bp.route('/extra/budget-totale', methods=['POST'])
def save_budget_totale():
    raw = request.form.get('budget_totale', '0').replace(',', '.').strip() or '0'
    try:
        val = max(float(raw), 0.0)
    except ValueError:
        val = 0.0
    with finance_db() as conn:
        set_setting(conn, BUDGET_TOTAL_KEY, val)
        conn.commit()
    flash(f'Budget extra totale impostato a € {val:.2f}.', 'success')
    return redirect(url_for('extra.index'))


@extra_bp.route('/extra/budget-categorie', methods=['POST'])
def save_budget_categorie():
    with finance_db() as conn:
        cats = q(conn, "SELECT id FROM category WHERE type='extra'")
        total = 0.0
        values = {}
        for (cat_id,) in cats:
            raw = request.form.get(f'budget_{cat_id}', '0').replace(',', '.').strip() or '0'
            try:
                val = max(float(raw), 0.0)
            except ValueError:
                val = 0.0
            values[cat_id] = val
            total += val
        for cat_id, val in values.items():
            conn.execute("UPDATE category SET budget=? WHERE id=?", (val, cat_id))
        budget_total_set = get_setting(conn, BUDGET_TOTAL_KEY, 0.0)
        conn.commit()

    # Non blocchiamo il salvataggio se si sfora: sono i numeri
    # dell'utente, non un vincolo imposto dallo strumento. Segnaliamo e
    # basta, come già succede altrove nell'app per un residuo negativo.
    if budget_total_set > 0 and total > budget_total_set + 0.005:
        flash(f'Budget categorie salvati, ma la somma (€ {total:.2f}) supera '
              f'il budget totale (€ {budget_total_set:.2f}) di € {total - budget_total_set:.2f}.',
              'warning')
    else:
        flash('Budget delle categorie extra aggiornati.', 'success')
    return redirect(url_for('extra.index'))
