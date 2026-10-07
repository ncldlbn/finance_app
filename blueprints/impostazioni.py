from flask import Blueprint, render_template, request, flash, redirect, url_for
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from db import finance_db
from helpers import q, get_setting, get_setting_str, set_setting

impostazioni_bp = Blueprint('impostazioni', __name__)

SAVINGS_GOAL_VALUE_KEY  = 'savings_goal_value'
SAVINGS_GOAL_PERIOD_KEY = 'savings_goal_period'
EXTRA_BUDGET_VALUE_KEY  = 'extra_budget_value'
EXTRA_BUDGET_PERIOD_KEY = 'extra_budget_period'
ESSENTIAL_BUDGET_VALUE_KEY  = 'essential_budget_value'
ESSENTIAL_BUDGET_PERIOD_KEY = 'essential_budget_period'

# I tre budget: (chiave valore, chiave periodo, prefisso dei campi del form)
BUDGETS = {
    'essential': (ESSENTIAL_BUDGET_VALUE_KEY, ESSENTIAL_BUDGET_PERIOD_KEY),
    'extra':     (EXTRA_BUDGET_VALUE_KEY, EXTRA_BUDGET_PERIOD_KEY),
    'savings':   (SAVINGS_GOAL_VALUE_KEY, SAVINGS_GOAL_PERIOD_KEY),
}


@impostazioni_bp.route('/impostazioni')
def index():
    with finance_db() as conn:
        cats = q(conn, "SELECT id, type, category, COALESCE(budget, 0) FROM category ORDER BY type, category")
        budgets = {name: {'value': get_setting(conn, vk, 0.0),
                          'period': get_setting_str(conn, pk, 'annuale')}
                   for name, (vk, pk) in BUDGETS.items()}
    essential = [(r[0], r[2], r[3]) for r in cats if r[1] == 'essential']
    extra     = [(r[0], r[2], r[3]) for r in cats if r[1] == 'extra']
    return render_template('impostazioni.html', essential=essential, extra=extra, budgets=budgets)


@impostazioni_bp.route('/impostazioni/budget', methods=['POST'])
def save_budget():
    """Salva in un colpo solo i tre budget (necessità, extra, risparmio): ognuno ha un
    importo e un periodo (mensile o annuale; l'annuale è il mensile x 12)."""
    saved = {}
    with finance_db() as conn:
        for name, (vk, pk) in BUDGETS.items():
            raw = request.form.get(f'{name}_value', '0').replace(',', '.').strip() or '0'
            try:
                val = max(float(raw), 0.0)
            except ValueError:
                val = 0.0
            period = request.form.get(f'{name}_period', 'annuale')
            if period not in ('mensile', 'annuale'):
                period = 'annuale'
            set_setting(conn, vk, val)
            set_setting(conn, pk, period)
            saved[name] = (val, period)
        conn.commit()
    flash('Budget salvato.', 'success')
    return redirect(url_for('impostazioni.index'))


@impostazioni_bp.route('/impostazioni/add_category', methods=['POST'])
def add_category():
    name = request.form.get('name', '').strip()
    tipo = request.form.get('type', '')
    if not name:
        flash('Inserisci un nome per la categoria.', 'error')
        return redirect(url_for('impostazioni.index'))
    if tipo not in ('essential', 'extra'):
        flash('Tipo non valido.', 'error')
        return redirect(url_for('impostazioni.index'))
    with finance_db() as conn:
        existing = conn.execute(
            "SELECT id FROM category WHERE type=? AND category=? AND user_id=1",
            (tipo, name)
        ).fetchone()
        if existing:
            flash(f'La categoria "{name}" esiste già.', 'warning')
        else:
            conn.execute(
                "INSERT INTO category (user_id, type, category, budget) VALUES (1,?,?,0)",
                (tipo, name))
            conn.commit()
            flash(f'Categoria "{name}" aggiunta.', 'success')
    return redirect(url_for('impostazioni.index'))


@impostazioni_bp.route('/impostazioni/save', methods=['POST'])
def save():
    with finance_db() as conn:
        cats = q(conn, "SELECT id FROM category")
        for (cat_id,) in cats:
            raw = request.form.get(f'budget_{cat_id}', '0').replace(',', '.').strip() or '0'
            try:
                val = float(raw)
            except ValueError:
                val = 0.0
            conn.execute("UPDATE category SET budget=? WHERE id=?", (val, cat_id))
        conn.commit()
    flash('Budget aggiornati.', 'success')
    return redirect(url_for('impostazioni.index'))
