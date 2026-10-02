"""Pagina Extra: monitoraggio della spesa discrezionale.

Il budget è a scendere: un totale annuale unico, consumato dalla spesa
delle categorie extra.
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
    """Un solo anello per il totale extra, con una barretta radiale
    all'angolo di oggi nell'anno: dove l'arco colorato supera la barretta si
    sta spendendo più in fretta del calendario. Sempre ancorata a oggi: un
    ritmo ha senso solo per l'anno in corso."""
    budget_total_set = get_setting(conn, BUDGET_TOTAL_KEY, 0.0)

    result = {
        'available': budget_total_set > 0,
        'budget_total_set': round(budget_total_set, 2),
        'spent_total': 0, 'pct_total': 0,
        'residuo_totale': 0, 'residuo_mensile': 0,
        'today_angle': 0, 'today_label': '',
    }
    if not result['available']:
        return result

    spent_total = round(q(conn, """
        SELECT COALESCE(SUM(e.euro),0) FROM expenses e
        JOIN category c ON e.category = c.category COLLATE NOCASE
        WHERE e.user_id=1 AND strftime('%Y',e.date)=? AND c.type='extra'""",
        (str(today.year),))[0][0], 2)

    residuo_totale = round(budget_total_set - spent_total, 2)
    yr_len = 366 if calendar.isleap(today.year) else 365
    today_doy = today.timetuple().tm_yday
    # Giorni ancora da vivere quest'anno: almeno 1, per non dividere per
    # zero il 31 dicembre.
    giorni_rimanenti = max(yr_len - today_doy, 1)
    residuo_mensile = round(residuo_totale / giorni_rimanenti * 30, 2)

    result.update(
        spent_total=spent_total,
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
