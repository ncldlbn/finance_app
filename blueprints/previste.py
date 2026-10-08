"""Spese previste: griglia di 12 mesi consecutivi (scorrevole) dove
annotare le spese che si prevede di fare. Sono solo promemoria: vivono in
una tabella a parte (planned_expenses) e non compaiono in Elenco né nelle
statistiche finché non vengono convertite in spesa vera."""
from flask import Blueprint, render_template, request, redirect, url_for, flash
import sys, os, re
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from db import finance_db
from helpers import q, MESI_IT_FULL, category_info
from validators import ValidationError, parse_amount, parse_date, parse_text, parse_ym

previste_bp = Blueprint('previste', __name__)

_MONTH_RE = re.compile(r'^\d{4}-(0[1-9]|1[0-2])$')


def _shift(ym, delta):
    """'YYYY-MM' spostato di delta mesi."""
    y, m = int(ym[:4]), int(ym[5:])
    idx = y * 12 + (m - 1) + delta
    return f"{idx // 12}-{idx % 12 + 1:02d}"


def _valid_month(value):
    return bool(value) and bool(_MONTH_RE.match(value))


def _back(start, n=''):
    n = n if n in ('4', '12') else '4'
    return redirect(url_for('previste.index', start=start, n=n) if _valid_month(start)
                    else url_for('previste.index', n=n))


@previste_bp.route('/previste')
def index():
    today = datetime.today()
    cur = f"{today.year}-{today.month:02d}"
    start = request.args.get('start', cur)
    if not _valid_month(start):
        start = cur
    n = request.args.get('n', '4')
    if n not in ('4', '12'):
        n = '4'
    span = int(n)
    months = [_shift(start, i) for i in range(span)]

    with finance_db() as conn:
        rows = q(conn, "SELECT id, month, euro, description, category, due_date "
                       "FROM planned_expenses WHERE user_id=current_uid() AND month BETWEEN ? AND ? "
                       "ORDER BY CASE WHEN due_date='' THEN 1 ELSE 0 END, due_date, id",
                 (months[0], months[-1]))
        cats = q(conn, "SELECT type, category FROM category WHERE user_id=current_uid() ORDER BY type, category COLLATE NOCASE")

    type_of = {c[1].lower(): c[0] for c in cats}
    items = {m: [] for m in months}
    for r in rows:
        items[r[1]].append({'id': r[0], 'euro': r[2], 'description': r[3],
                            'category': r[4], 'due_date': r[5],
                            # '' se la categoria (facoltativa) non è stata scelta
                            'type': type_of.get(r[4].lower(), '')})

    def total(m, t):
        return round(sum(i['euro'] for i in items[m] if i['type'] == t), 2)

    grid = [{'ym': m, 'label': f"{MESI_IT_FULL[int(m[5:])]} {m[:4]}",
             'is_current': m == cur, 'items': items[m],
             'total': round(sum(i['euro'] for i in items[m]), 2),
             'essential': total(m, 'essential'), 'extra': total(m, 'extra'),
             'other': total(m, '')} for m in months]

    return render_template('previste.html', grid=grid, start=start, n=n,
        prev1=_shift(start, -1), next1=_shift(start, 1),
        prev_span=_shift(start, -span), next_span=_shift(start, span), cur=cur,
        essential_cats=[c[1] for c in cats if c[0] == 'essential'],
        extra_cats=[c[1] for c in cats if c[0] == 'extra'],
        today=today.date().isoformat())


@previste_bp.route('/previste/add', methods=['POST'])
def add():
    start = request.form.get('start', '')
    n = request.form.get('n', '')
    month       = parse_ym(request.form.get('month'))
    euro        = parse_amount(request.form.get('euro'), positive=True, allow_zero=False)
    description = parse_text(request.form.get('description'), label='Descrizione', required=True)
    due_raw     = (request.form.get('due_date') or '').strip()
    due_date    = parse_date(due_raw, 'due_date', 'Scadenza') if due_raw else ''
    if due_date and not due_date.startswith(month):
        raise ValidationError('La scadenza deve cadere nel mese scelto.', 'due_date')
    with finance_db() as conn:
        category = ''
        if (request.form.get('category') or '').strip():            # la categoria è facoltativa
            category, _ = category_info(conn, request.form.get('category'))
        conn.execute("INSERT INTO planned_expenses (user_id, month, euro, description, category, due_date) "
                     "VALUES (current_uid(),?,?,?,?,?)", (month, euro, description, category, due_date))
        conn.commit()
    flash('Spesa prevista aggiunta.', 'success')
    return _back(start, n)


@previste_bp.route('/previste/<int:pid>/delete', methods=['POST'])
def delete(pid):
    with finance_db() as conn:
        conn.execute("DELETE FROM planned_expenses WHERE id=? AND user_id=current_uid()", (pid,))
        conn.commit()
    flash('Spesa prevista eliminata.', 'success')
    return _back(request.form.get('start', ''), request.form.get('n', ''))


@previste_bp.route('/previste/<int:pid>/convert', methods=['POST'])
def convert(pid):
    """Trasforma la previsione in spesa vera (data = scadenza se c'è, altrimenti
    oggi) e la rimuove dalle previste. Serve una categoria: le spese vere
    senza categoria non comparirebbero nei grafici."""
    start = request.form.get('start', '')
    n = request.form.get('n', '')
    with finance_db() as conn:
        row = conn.execute("SELECT euro, description, category, due_date FROM planned_expenses "
                           "WHERE id=? AND user_id=current_uid()", (pid,)).fetchone()
        if not row:
            return _back(start, n)
        euro, description, category, due_date = row
        cat = conn.execute("SELECT type FROM category WHERE user_id=current_uid() AND category=? COLLATE NOCASE",
                           (category,)).fetchone() if category else None
        if not cat:
            flash('Per convertire serve una categoria: assegnala (elimina e reinserisci la previsione con la categoria).', 'error')
            return _back(start, n)
        date = due_date or datetime.today().date().isoformat()
        conn.execute("INSERT INTO expenses (date, euro, category, description, user_id, type) "
                     "VALUES (?,?,?,?,current_uid(),?)", (date, euro, category, description, cat[0]))
        conn.execute("DELETE FROM planned_expenses WHERE id=? AND user_id=current_uid()", (pid,))
        conn.commit()
    flash(f'Convertita in spesa: € {euro:.2f} · {category}.', 'success')
    return _back(start, n)
