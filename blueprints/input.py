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


def _get_recurring(conn):
    rows = conn.execute(
        "SELECT id, day_of_month, euro, type, category, description, auto_insert, active "
        "FROM recurring_expenses WHERE user_id=1 ORDER BY day_of_month, category"
    ).fetchall()
    keys = ['id', 'day_of_month', 'euro', 'type', 'category', 'description', 'auto_insert', 'active']
    return [dict(zip(keys, r)) for r in rows]


def _already_inserted(conn, rule, year, month):
    """True se esiste già una spesa corrispondente a questa regola nel mese dato."""
    return conn.execute(
        "SELECT id FROM expenses WHERE user_id=1 AND strftime('%Y-%m', date)=? "
        "AND euro=? AND category=?",
        (f"{year}-{month:02d}", rule['euro'], rule['category'])
    ).fetchone() is not None


def _insert_rule(conn, rule, today):
    date_str = f"{today.year}-{today.month:02d}-{rule['day_of_month']:02d}"
    conn.execute(
        "INSERT INTO expenses (date, euro, category, description, user_id, type) VALUES (?,?,?,?,1,?)",
        (date_str, rule['euro'], rule['category'], rule['description'], rule['type']))


def run_auto_insert(today=None):
    """Inserisce silenziosamente le regole auto_insert=1 attive non ancora eseguite questo mese."""
    if today is None:
        today = datetime.today()
    inserted = []
    with finance_db() as conn:
        rules = _get_recurring(conn)
        for rule in rules:
            if not rule['active'] or not rule['auto_insert']:
                continue
            if rule['day_of_month'] > today.day:
                continue
            if _already_inserted(conn, rule, today.year, today.month):
                continue
            _insert_rule(conn, rule, today)
            inserted.append(rule['description'] or rule['category'])
        if inserted:
            conn.commit()
    return inserted


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

        elif action == 'add_recurring':
            try:
                day  = int(request.form.get('day_of_month', 0))
                euro = float(request.form.get('euro', '0').replace(',', '.'))
            except ValueError:
                flash('Dati non validi.', 'error')
                return redirect(url_for('input.index', tab='ricorrenti'))
            tipo        = request.form.get('tipo', '')
            category    = request.form.get('category', '').strip()
            description = request.form.get('description', '').strip()
            auto_insert = 1 if request.form.get('auto_insert') else 0
            if not (1 <= day <= 28) or euro <= 0 or not category:
                flash('Compila tutti i campi correttamente (giorno tra 1 e 28).', 'error')
                return redirect(url_for('input.index', tab='ricorrenti'))
            with finance_db() as conn:
                conn.execute(
                    "INSERT INTO recurring_expenses (user_id, day_of_month, euro, type, category, description, auto_insert, active) "
                    "VALUES (1,?,?,?,?,?,?,1)",
                    (day, euro, tipo, category, description, auto_insert))
                conn.commit()
            flash('Regola aggiunta!', 'success')
            return redirect(url_for('input.index', tab='ricorrenti'))

        elif action == 'edit_recurring':
            rid = int(request.form.get('id'))
            try:
                day  = int(request.form.get('day_of_month', 0))
                euro = float(request.form.get('euro', '0').replace(',', '.'))
            except ValueError:
                flash('Dati non validi.', 'error')
                return redirect(url_for('input.index', tab='ricorrenti'))
            if not (1 <= day <= 28) or euro <= 0:
                flash('Giorno deve essere tra 1 e 28 e importo maggiore di zero.', 'error')
                return redirect(url_for('input.index', tab='ricorrenti'))
            auto_insert = 1 if request.form.get('auto_insert') else 0
            with finance_db() as conn:
                conn.execute(
                    "UPDATE recurring_expenses SET day_of_month=?, euro=?, auto_insert=? WHERE id=? AND user_id=1",
                    (day, euro, auto_insert, rid))
                conn.commit()
            flash('Regola aggiornata.', 'success')
            return redirect(url_for('input.index', tab='ricorrenti'))

        elif action == 'delete_recurring':
            rid = int(request.form.get('id'))
            with finance_db() as conn:
                conn.execute("DELETE FROM recurring_expenses WHERE id=? AND user_id=1", (rid,))
                conn.commit()
            flash('Regola eliminata.', 'success')
            return redirect(url_for('input.index', tab='ricorrenti'))

        elif action == 'toggle_recurring':
            rid    = int(request.form.get('id'))
            active = int(request.form.get('active'))
            with finance_db() as conn:
                conn.execute("UPDATE recurring_expenses SET active=? WHERE id=? AND user_id=1", (active, rid))
                conn.commit()
            return redirect(url_for('input.index', tab='ricorrenti'))

        elif action == 'confirm_recurring':
            today = datetime.today()
            ids   = request.form.getlist('rule_ids')
            if not ids:
                return redirect(url_for('input.index', tab='spese'))
            with finance_db() as conn:
                rules = _get_recurring(conn)
                rules_map = {r['id']: r for r in rules}
                count = 0
                for rid in ids:
                    rule = rules_map.get(int(rid))
                    if not rule:
                        continue
                    if _already_inserted(conn, rule, today.year, today.month):
                        continue
                    _insert_rule(conn, rule, today)
                    count += 1
                if count:
                    conn.commit()
            flash(f'{count} {"spesa inserita" if count == 1 else "spese inserite"}!', 'success')
            return redirect(url_for('input.index', tab='spese'))

    today          = datetime.today()
    today_str      = today.date().isoformat()
    essential_cats = get_categories_by_type('essential')
    extra_cats     = get_categories_by_type('extra')
    active_tab     = request.args.get('tab', 'spese')
    anni_range     = list(range(today.year - 5, today.year + 2))

    # Catch-up auto-insert
    auto_inserted = run_auto_insert(today)
    if auto_inserted:
        flash(f'Inserite automaticamente: {", ".join(auto_inserted)}.', 'info')

    # Regole in attesa di conferma (auto_insert=False, attive, giorno <= oggi, non ancora inserite)
    with finance_db() as conn:
        all_rules    = _get_recurring(conn)
        pending = [
            r for r in all_rules
            if r['active'] and not r['auto_insert']
            and r['day_of_month'] <= today.day
            and not _already_inserted(conn, r, today.year, today.month)
        ]

    return render_template('input.html',
        today=today_str,
        today_obj=today,
        essential_cats=essential_cats,
        extra_cats=extra_cats,
        active_tab=active_tab,
        anni_range=anni_range,
        mesi_it=_MESI_IT,
        labels=_PATRIMONIO_LABELS,
        all_rules=all_rules,
        pending=pending,
    )
