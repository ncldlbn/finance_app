from flask import Blueprint, render_template, request, flash, redirect, url_for
import sqlite3
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from db import get_finance_conn

input_bp = Blueprint('input', __name__)

def get_categories_by_type(cat_type):
    conn = get_finance_conn()
    cur = conn.execute("SELECT category FROM category WHERE type=? ORDER BY category", (cat_type,))
    cats = [row[0] for row in cur.fetchall()]
    conn.close()
    return cats

@input_bp.route('/input', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        action = request.form.get('action')

        if action == 'add_expense':
            date_val   = request.form.get('date')
            euro       = request.form.get('euro', '0').replace(',', '.')
            tipo       = request.form.get('tipo')  # essential / extra
            category   = request.form.get('category')
            description = request.form.get('description', '')
            try:
                euro_f = float(euro)
            except ValueError:
                flash('Importo non valido.', 'error')
                return redirect(url_for('input.index'))

            conn = get_finance_conn()
            c = conn.cursor()
            c.execute("SELECT id FROM expenses WHERE date=? AND euro=? AND category=? AND user_id=1",
                      (date_val, euro_f, category))
            if c.fetchone():
                flash('⚠️ Questa spesa è già presente!', 'warning')
            else:
                c.execute("INSERT INTO expenses (date, euro, category, description, user_id, type) VALUES (?,?,?,?,1,?)",
                          (date_val, euro_f, category, description, tipo))
                conn.commit()
                flash('💾 Spesa inserita correttamente!', 'success')
            conn.close()
            return redirect(url_for('input.index', tab='spese'))

        elif action == 'add_income':
            date_val    = request.form.get('date')
            euro        = request.form.get('euro', '0').replace(',', '.')
            description = request.form.get('description', '')
            try:
                euro_f = float(euro)
            except ValueError:
                flash('Importo non valido.', 'error')
                return redirect(url_for('input.index'))

            conn = get_finance_conn()
            c = conn.cursor()
            c.execute("SELECT id FROM incomes WHERE date=? AND euro=? AND user_id=1", (date_val, euro_f))
            if c.fetchone():
                flash('⚠️ Questa entrata è già presente!', 'warning')
            else:
                c.execute("INSERT INTO incomes (date, euro, description, user_id) VALUES (?,?,?,1)",
                          (date_val, euro_f, description))
                conn.commit()
                flash('💾 Entrata inserita correttamente!', 'success')
            conn.close()
            return redirect(url_for('input.index', tab='entrate'))

    from datetime import date
    today = date.today().isoformat()
    essential_cats = get_categories_by_type('essential')
    extra_cats     = get_categories_by_type('extra')
    active_tab     = request.args.get('tab', 'spese')

    return render_template('input.html',
                           today=today,
                           essential_cats=essential_cats,
                           extra_cats=extra_cats,
                           active_tab=active_tab)
