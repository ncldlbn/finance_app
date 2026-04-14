from flask import Blueprint, render_template, request, flash, redirect, url_for
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from db import finance_db
from helpers import q

impostazioni_bp = Blueprint('impostazioni', __name__)


@impostazioni_bp.route('/impostazioni')
def index():
    with finance_db() as conn:
        cats = q(conn, "SELECT id, type, category, COALESCE(budget, 0) FROM category ORDER BY type, category")
    essential = [(r[0], r[2], r[3]) for r in cats if r[1] == 'essential']
    extra     = [(r[0], r[2], r[3]) for r in cats if r[1] == 'extra']
    return render_template('impostazioni.html', essential=essential, extra=extra)


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
