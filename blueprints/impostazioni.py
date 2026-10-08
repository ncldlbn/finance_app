from flask import Blueprint, render_template, request, flash, redirect, url_for
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from db import finance_db
from datetime import datetime
from helpers import q, all_years, budget_row, BUDGET_KINDS
from validators import parse_amount, parse_int, parse_text, year_arg, YEAR_MIN, YEAR_MAX

impostazioni_bp = Blueprint('impostazioni', __name__)


@impostazioni_bp.route('/impostazioni')
def index():
    this_year = datetime.now().year
    anno = year_arg('anno', this_year)
    with finance_db() as conn:
        cats = q(conn, "SELECT id, type, category, COALESCE(budget, 0) FROM category ORDER BY type, category")
        data_years = [int(y) for y in all_years(conn)]
        # Budget validi per l'anno scelto; `from_year` dice da quale anno vengono se l'anno non ne ha di propri.
        budgets = {}
        for kind in BUDGET_KINDS:
            row = budget_row(conn, anno, kind)
            budgets[kind] = {'value': row[0] if row else 0.0, 'period': row[1] if row else 'annuale',
                             'from_year': row[2] if row else None}
        explicit = {r[0] for r in q(conn, "SELECT kind FROM budgets WHERE year=?", (anno,))}
    years = sorted({this_year + 1, this_year, anno, *data_years}, reverse=True)
    essential = [(r[0], r[2], r[3]) for r in cats if r[1] == 'essential']
    extra     = [(r[0], r[2], r[3]) for r in cats if r[1] == 'extra']
    return render_template('impostazioni.html', essential=essential, extra=extra, budgets=budgets,
                           budget_year=anno, budget_years=years, inherited=[k for k in BUDGET_KINDS if k not in explicit])


@impostazioni_bp.route('/impostazioni/budget', methods=['POST'])
def save_budget():
    """Salva i tre budget (necessità, extra, risparmio) per l'anno scelto: importo e periodo
    (mensile o annuale; l'annuale è il mensile x 12). Gli anni successivi senza budget propri
    ereditano questi."""
    anno = parse_int(request.form.get('year'), 'year', 'Anno', YEAR_MIN, YEAR_MAX)
    with finance_db() as conn:
        for kind in BUDGET_KINDS:
            val = parse_amount(request.form.get(f'{kind}_value') or '0', f'{kind}_value', 'Budget', positive=True)
            period = request.form.get(f'{kind}_period', 'annuale')
            if period not in ('mensile', 'annuale'):
                period = 'annuale'
            conn.execute("INSERT INTO budgets (year, kind, value, period) VALUES (?,?,?,?) "
                         "ON CONFLICT(year, kind) DO UPDATE SET value=excluded.value, period=excluded.period",
                         (anno, kind, val, period))
        conn.commit()
    flash(f'Budget {anno} salvato.', 'success')
    return redirect(url_for('impostazioni.index', anno=anno))


@impostazioni_bp.route('/impostazioni/add_category', methods=['POST'])
def add_category():
    name = parse_text(request.form.get('name'), 'name', 'Nome', max_len=60)
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
