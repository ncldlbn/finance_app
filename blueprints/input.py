from flask import Blueprint, render_template, request, flash, redirect, url_for
from datetime import datetime
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from db import finance_db

input_bp = Blueprint('input', __name__)

_PATRIMONIO_FIELDS = [
    'bcc', 'bbva', 'directa', 'deposito', 'obblig', 'etf_etc',
    'debito', 'credito', 'cauzioni', 'tfr', 'fon_te',
]
_PATRIMONIO_LABELS = {
    'bcc': 'BCC', 'bbva': 'BBVA', 'directa': 'Directa',
    'deposito': 'Deposito', 'obblig': 'Obbligazioni', 'etf_etc': 'ETF / ETC',
    'debito': 'Debito', 'credito': 'Credito', 'cauzioni': 'Cauzioni',
    'tfr': 'TFR', 'fon_te': 'Fon.Te.',
}
_MESI_IT = [
    '', 'Gennaio', 'Febbraio', 'Marzo', 'Aprile', 'Maggio', 'Giugno',
    'Luglio', 'Agosto', 'Settembre', 'Ottobre', 'Novembre', 'Dicembre',
]


def get_categories_by_type(cat_type):
    with finance_db() as conn:
        rows = conn.execute(
            "SELECT category FROM category WHERE type=? ORDER BY category", (cat_type,)
        ).fetchall()
    return [row[0] for row in rows]


def _parse_patrimonio_form():
    vals = {}
    for f in _PATRIMONIO_FIELDS:
        raw = request.form.get(f, '0').replace(',', '.').strip() or '0'
        try:
            vals[f] = float(raw)
        except ValueError:
            vals[f] = 0.0
    return vals


@input_bp.route('/input', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        action = request.form.get('action')

        if action == 'add_expense':
            date_val    = request.form.get('date')
            euro        = request.form.get('euro', '0').replace(',', '.')
            tipo        = request.form.get('tipo')
            category    = request.form.get('category')
            description = request.form.get('description', '')
            try:
                euro_f = float(euro)
            except ValueError:
                flash('Importo non valido.', 'error')
                return redirect(url_for('input.index'))

            with finance_db() as conn:
                existing = conn.execute(
                    "SELECT id FROM expenses WHERE date=? AND euro=? AND category=? AND user_id=1",
                    (date_val, euro_f, category)
                ).fetchone()
                if existing:
                    flash('Questa spesa è già presente!', 'warning')
                else:
                    conn.execute(
                        "INSERT INTO expenses (date, euro, category, description, user_id, type) VALUES (?,?,?,?,1,?)",
                        (date_val, euro_f, category, description, tipo))
                    conn.commit()
                    flash('Spesa inserita correttamente!', 'success')
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

            with finance_db() as conn:
                existing = conn.execute(
                    "SELECT id FROM incomes WHERE date=? AND euro=? AND description=? AND user_id=1",
                    (date_val, euro_f, description)
                ).fetchone()
                if existing:
                    flash('Questa entrata è già presente!', 'warning')
                else:
                    conn.execute(
                        "INSERT INTO incomes (date, euro, description, user_id) VALUES (?,?,?,1)",
                        (date_val, euro_f, description))
                    conn.commit()
                    flash('Entrata inserita correttamente!', 'success')
            return redirect(url_for('input.index', tab='entrate'))

        elif action == 'add_etf_buy':
            date_val = request.form.get('date')
            ticker   = request.form.get('ticker', '').upper().strip()
            try:
                qty   = float(request.form.get('quantity', '0'))
                price = float(request.form.get('price', '0'))
            except ValueError:
                flash('Dati non validi.', 'error')
                return redirect(url_for('input.index', tab='etf'))
            if not ticker or qty <= 0 or price <= 0:
                flash('Compila tutti i campi correttamente.', 'error')
                return redirect(url_for('input.index', tab='etf'))
            with finance_db() as conn:
                conn.execute(
                    "INSERT INTO transactions (date, ticker, quantity, price) VALUES (?,?,?,?)",
                    (date_val, ticker, qty, price))
                conn.commit()
            flash('Acquisto registrato!', 'success')
            return redirect(url_for('input.index', tab='etf'))

        elif action == 'add_etf_sell':
            date_val = request.form.get('date')
            ticker   = request.form.get('ticker', '').upper().strip()
            try:
                qty   = float(request.form.get('quantity', '0'))
                price = float(request.form.get('price', '0'))
            except ValueError:
                flash('Dati non validi.', 'error')
                return redirect(url_for('input.index', tab='etf'))
            if not ticker or qty <= 0 or price <= 0:
                flash('Compila tutti i campi correttamente.', 'error')
                return redirect(url_for('input.index', tab='etf'))
            with finance_db() as conn:
                conn.execute(
                    "INSERT INTO transactions (date, ticker, quantity, price) VALUES (?,?,?,?)",
                    (date_val, ticker, -qty, price))
                conn.commit()
            flash('Vendita registrata!', 'success')
            return redirect(url_for('input.index', tab='etf'))

        elif action == 'add_patrimonio':
            anno = int(request.form.get('anno', datetime.today().year))
            mese = int(request.form.get('mese', datetime.today().month))
            vals = _parse_patrimonio_form()
            with finance_db() as conn:
                if conn.execute(
                    "SELECT id FROM patrimonio WHERE anno=? AND mese=?", (anno, mese)
                ).fetchone():
                    flash(f'Esiste già un record per {mese}/{anno}. Modificalo dalla pagina Patrimonio.', 'error')
                    return redirect(url_for('input.index', tab='patrimonio'))
                conn.execute(
                    f"INSERT INTO patrimonio (anno, mese, {', '.join(_PATRIMONIO_FIELDS)}) "
                    f"VALUES (?,?,{','.join(['?']*len(_PATRIMONIO_FIELDS))})",
                    [anno, mese] + [vals[f] for f in _PATRIMONIO_FIELDS])
                conn.commit()
            flash('Mese aggiunto!', 'success')
            return redirect(url_for('input.index', tab='patrimonio'))

    today          = datetime.today()
    today_str      = today.date().isoformat()
    essential_cats = get_categories_by_type('essential')
    extra_cats     = get_categories_by_type('extra')
    active_tab     = request.args.get('tab', 'spese')
    anni_range     = list(range(today.year - 5, today.year + 2))

    return render_template('input.html',
        today=today_str,
        today_obj=today,
        essential_cats=essential_cats,
        extra_cats=extra_cats,
        active_tab=active_tab,
        anni_range=anni_range,
        mesi_it=_MESI_IT,
        labels=_PATRIMONIO_LABELS,
    )
