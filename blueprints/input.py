from flask import Blueprint, render_template, request, flash, redirect, url_for, g
from datetime import datetime
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from db import finance_db
from helpers import category_info
from validators import (ValidationError, parse_amount, parse_date, parse_int, parse_text, parse_id,
                        parse_year_month)

input_bp = Blueprint('input', __name__)

_PATRIMONIO_FIELDS = [
    'bcc', 'bbva', 'directa', 'deposito', 'obblig', 'etf_etc',
    'tfr', 'fon_te',
]
_PATRIMONIO_LABELS = {
    'bcc': 'BCC', 'bbva': 'BBVA', 'directa': 'Directa',
    'deposito': 'Deposito', 'obblig': 'Obbligazioni', 'etf_etc': 'ETF / ETC',
    'tfr': 'TFR', 'fon_te': 'Fon.Te.',
}
_MESI_IT = [
    '', 'Gennaio', 'Febbraio', 'Marzo', 'Aprile', 'Maggio', 'Giugno',
    'Luglio', 'Agosto', 'Settembre', 'Ottobre', 'Novembre', 'Dicembre',
]


def get_categories_by_type(cat_type):
    with finance_db() as conn:
        rows = conn.execute(
            "SELECT category FROM category WHERE user_id=current_uid() AND type=? ORDER BY category", (cat_type,)
        ).fetchall()
    return [row[0] for row in rows]


def _parse_patrimonio_form():
    """Importi del patrimonio: campo vuoto = 0; sono ammessi i negativi (conto in rosso)."""
    return {f: parse_amount(request.form.get(f) or '0', f, _PATRIMONIO_LABELS[f]) for f in _PATRIMONIO_FIELDS}


def _get_recurring(conn):
    rows = conn.execute(
        "SELECT id, day_of_month, euro, type, category, description, auto_insert, active "
        "FROM recurring_expenses WHERE user_id=current_uid() ORDER BY day_of_month, category"
    ).fetchall()
    keys = ['id', 'day_of_month', 'euro', 'type', 'category', 'description', 'auto_insert', 'active']
    return [dict(zip(keys, r)) for r in rows]


def _already_inserted(conn, rule, year, month):
    """True se esiste già una spesa corrispondente a questa regola nel mese dato."""
    return conn.execute(
        "SELECT id FROM expenses WHERE user_id=current_uid() AND strftime('%Y-%m', date)=? "
        "AND euro=? AND category=?",
        (f"{year}-{month:02d}", rule['euro'], rule['category'])
    ).fetchone() is not None


def _insert_rule(conn, rule, today):
    date_str = f"{today.year}-{today.month:02d}-{rule['day_of_month']:02d}"
    conn.execute(
        "INSERT INTO expenses (date, euro, category, description, user_id, type) VALUES (?,?,?,?,current_uid(),?)",
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
            date_val    = parse_date(request.form.get('date'))
            euro_f      = parse_amount(request.form.get('euro'), allow_zero=False)
            description = parse_text(request.form.get('description'))
            with finance_db() as conn:
                category, tipo = category_info(conn, request.form.get('category'))
                existing = conn.execute(
                    "SELECT id FROM expenses WHERE date=? AND euro=? AND category=? AND user_id=current_uid()",
                    (date_val, euro_f, category)
                ).fetchone()
                if existing:
                    flash('Questa spesa è già presente!', 'warning')
                else:
                    conn.execute(
                        "INSERT INTO expenses (date, euro, category, description, user_id, type) VALUES (?,?,?,?,current_uid(),?)",
                        (date_val, euro_f, category, description, tipo))
                    conn.commit()
                    flash('Spesa inserita correttamente!', 'success')
            return redirect(url_for('input.index', tab='spese'))

        elif action == 'add_income':
            date_val    = parse_date(request.form.get('date'))
            euro_f      = parse_amount(request.form.get('euro'), allow_zero=False)
            description = parse_text(request.form.get('description'))
            with finance_db() as conn:
                existing = conn.execute(
                    "SELECT id FROM incomes WHERE date=? AND euro=? AND description=? AND user_id=current_uid()",
                    (date_val, euro_f, description)
                ).fetchone()
                if existing:
                    flash('Questa entrata è già presente!', 'warning')
                else:
                    conn.execute(
                        "INSERT INTO incomes (date, euro, description, user_id) VALUES (?,?,?,current_uid())",
                        (date_val, euro_f, description))
                    conn.commit()
                    flash('Entrata inserita correttamente!', 'success')
            return redirect(url_for('input.index', tab='entrate'))

        elif action == 'add_patrimonio':
            anno, mese = parse_year_month(request.form.get('anno'), request.form.get('mese'))
            vals = _parse_patrimonio_form()
            with finance_db() as conn:
                if conn.execute(
                    "SELECT id FROM patrimonio WHERE user_id=current_uid() AND anno=? AND mese=?", (anno, mese)
                ).fetchone():
                    flash(f'Esiste già un record per {mese}/{anno}. Modificalo dalla pagina Patrimonio.', 'error')
                    return redirect(url_for('input.index', tab='patrimonio'))
                conn.execute(
                    f"INSERT INTO patrimonio (user_id, anno, mese, {', '.join(_PATRIMONIO_FIELDS)}) "
                    f"VALUES (current_uid(),?,?,{','.join(['?']*len(_PATRIMONIO_FIELDS))})",
                    [anno, mese] + [vals[f] for f in _PATRIMONIO_FIELDS])
                conn.commit()
            flash('Mese aggiunto!', 'success')
            return redirect(url_for('input.index', tab='patrimonio'))

        elif action == 'add_recurring':
            day         = parse_int(request.form.get('day_of_month'), 'day_of_month', 'Giorno del mese', 1, 28)
            euro        = parse_amount(request.form.get('euro'), positive=True, allow_zero=False)
            description = parse_text(request.form.get('description'))
            auto_insert = 1 if request.form.get('auto_insert') else 0
            with finance_db() as conn:
                category, tipo = category_info(conn, request.form.get('category'))
                conn.execute(
                    "INSERT INTO recurring_expenses (user_id, day_of_month, euro, type, category, description, auto_insert, active) "
                    "VALUES (current_uid(),?,?,?,?,?,?,1)",
                    (day, euro, tipo, category, description, auto_insert))
                conn.commit()
            flash('Regola aggiunta!', 'success')
            return redirect(url_for('input.index', tab='ricorrenti'))

        elif action == 'edit_recurring':
            rid         = parse_id(request.form.get('id'))
            day         = parse_int(request.form.get('day_of_month'), 'day_of_month', 'Giorno del mese', 1, 28)
            euro        = parse_amount(request.form.get('euro'), positive=True, allow_zero=False)
            description = parse_text(request.form.get('description'))
            auto_insert = 1 if request.form.get('auto_insert') else 0
            with finance_db() as conn:
                # Il tipo (necessità/extra) segue la categoria scelta.
                category, tipo = category_info(conn, request.form.get('category'))
                conn.execute(
                    "UPDATE recurring_expenses SET day_of_month=?, euro=?, type=?, category=?, "
                    "description=?, auto_insert=? WHERE id=? AND user_id=current_uid()",
                    (day, euro, tipo, category, description, auto_insert, rid))
                conn.commit()
            flash('Regola aggiornata.', 'success')
            return redirect(url_for('input.index', tab='ricorrenti'))

        elif action == 'delete_recurring':
            rid = parse_id(request.form.get('id'))
            with finance_db() as conn:
                conn.execute("DELETE FROM recurring_expenses WHERE id=? AND user_id=current_uid()", (rid,))
                conn.commit()
            flash('Regola eliminata.', 'success')
            return redirect(url_for('input.index', tab='ricorrenti'))

        elif action == 'toggle_recurring':
            rid    = parse_id(request.form.get('id'))
            active = parse_int(request.form.get('active'), 'active', 'Stato', 0, 1)
            with finance_db() as conn:
                conn.execute("UPDATE recurring_expenses SET active=? WHERE id=? AND user_id=current_uid()", (active, rid))
                conn.commit()
            return redirect(url_for('input.index', tab='ricorrenti'))

        elif action == 'confirm_recurring':
            today = datetime.today()
            ids   = [parse_id(x, 'rule_ids') for x in request.form.getlist('rule_ids')]
            if not ids:
                return redirect(url_for('input.index', tab='spese'))
            with finance_db() as conn:
                rules = _get_recurring(conn)
                rules_map = {r['id']: r for r in rules}
                count = 0
                for rid in ids:
                    rule = rules_map.get(rid)
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

        raise ValidationError('Azione non riconosciuta.')

    today          = datetime.today()
    today_str      = today.date().isoformat()
    essential_cats = get_categories_by_type('essential')
    extra_cats     = get_categories_by_type('extra')
    active_tab     = request.args.get('tab', 'spese')
    if active_tab not in ('spese', 'entrate', 'patrimonio', 'ricorrenti'):
        active_tab = 'spese'
    anni_range     = list(range(today.year - 5, today.year + 2))

    # Catch-up auto-insert
    # L'account demo è in sola lettura: niente inserimenti automatici nemmeno qui.
    auto_inserted = [] if g.user['is_demo'] else run_auto_insert(today)
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
