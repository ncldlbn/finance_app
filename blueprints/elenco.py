from flask import Blueprint, render_template, request, flash, redirect, url_for, Response
import csv, io, sys, os
from datetime import datetime
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from db import finance_db
from helpers import category_info
from validators import int_arg, parse_amount, parse_date, parse_text

elenco_bp = Blueprint('elenco', __name__)
PAGE_SIZE = 100


def get_expenses(filters=None, page=1):
    """page=None restituisce tutte le righe che soddisfano il filtro (export)."""
    base = """
        SELECT e.id, e.date, e.euro, e.category, e.description, COALESCE(c.type,'') as type
        FROM expenses e LEFT JOIN category c ON e.category = c.category
        WHERE e.user_id=1
    """
    params, conditions = [], []
    if filters:
        if filters.get('anno'):
            conditions.append("strftime('%Y',e.date)=?"); params.append(filters['anno'])
        if filters.get('mese'):
            conditions.append("strftime('%m',e.date)=?"); params.append(filters['mese'].zfill(2))
        if filters.get('cat'):
            conditions.append("e.category=?"); params.append(filters['cat'])
        if filters.get('desc'):
            conditions.append("LOWER(e.description) LIKE ?"); params.append(f"%{filters['desc'].lower()}%")
    if conditions:
        base += " AND " + " AND ".join(conditions)

    with finance_db() as conn:
        total, tot_sum = conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(euro),0) FROM (" + base + ")", params).fetchone()
        order = " ORDER BY e.date DESC, e.rowid DESC"
        rows  = conn.execute(
            base + order + (" LIMIT ? OFFSET ?" if page else ""),
            params + ([PAGE_SIZE, (page - 1) * PAGE_SIZE] if page else [])
        ).fetchall()

    expenses = [dict(id=r[0], date=r[1], euro=r[2], category=r[3], description=r[4] or '', type=r[5])
                for r in rows]
    return expenses, total, tot_sum


def get_incomes_filtered(filters=None, page=1):
    base   = "SELECT id, date, euro, description FROM incomes WHERE user_id=1"
    params, conditions = [], []
    if filters:
        if filters.get('anno'):
            conditions.append("strftime('%Y',date)=?"); params.append(filters['anno'])
        if filters.get('mese'):
            conditions.append("strftime('%m',date)=?"); params.append(filters['mese'].zfill(2))
        if filters.get('desc'):
            conditions.append("LOWER(description) LIKE ?"); params.append(f"%{filters['desc'].lower()}%")
    if conditions:
        base += " AND " + " AND ".join(conditions)

    with finance_db() as conn:
        total, tot_sum = conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(euro),0) FROM (" + base + ")", params).fetchone()
        order = " ORDER BY date DESC, rowid DESC"
        rows  = conn.execute(
            base + order + (" LIMIT ? OFFSET ?" if page else ""),
            params + ([PAGE_SIZE, (page - 1) * PAGE_SIZE] if page else [])
        ).fetchall()

    incomes = [dict(id=r[0], date=r[1], euro=r[2], description=r[3] or '') for r in rows]
    return incomes, total, tot_sum


def get_filter_options():
    with finance_db() as conn:
        anni_exp = [r[0] for r in conn.execute(
            "SELECT DISTINCT strftime('%Y',date) y FROM expenses WHERE user_id=1 ORDER BY y DESC").fetchall()]
        cats_exp = [r[0] for r in conn.execute(
            "SELECT DISTINCT category FROM expenses WHERE user_id=1 ORDER BY category").fetchall()]
        anni_inc = [r[0] for r in conn.execute(
            "SELECT DISTINCT strftime('%Y',date) y FROM incomes WHERE user_id=1 ORDER BY y DESC").fetchall()]
    return anni_exp, cats_exp, anni_inc


def get_all_categories():
    """Tutte le categorie disponibili, raggruppate per tipo (per il menu di modifica)."""
    with finance_db() as conn:
        rows = conn.execute(
            "SELECT category, type FROM category ORDER BY type, category").fetchall()
    return [dict(category=r[0], type=r[1]) for r in rows]


@elenco_bp.route('/elenco')
def index():
    active_tab = request.args.get('tab', 'spese')

    f_exp  = {k: request.args.get(k, '') for k in ('anno', 'mese', 'cat', 'desc')}
    page_s = int_arg('page_s', 1)
    expenses, total_exp, sum_exp = get_expenses(f_exp, page_s)
    pages_exp = max(1, (total_exp + PAGE_SIZE - 1) // PAGE_SIZE)
    if page_s > pages_exp:                       # pagina oltre la fine: si mostra l'ultima
        page_s = pages_exp
        expenses, total_exp, sum_exp = get_expenses(f_exp, page_s)

    f_inc  = {k: request.args.get(k + '_e', '') for k in ('anno', 'mese', 'desc')}
    page_e = int_arg('page_e', 1)
    incomes, total_inc, sum_inc = get_incomes_filtered(f_inc, page_e)
    pages_inc = max(1, (total_inc + PAGE_SIZE - 1) // PAGE_SIZE)
    if page_e > pages_inc:
        page_e = pages_inc
        incomes, total_inc, sum_inc = get_incomes_filtered(f_inc, page_e)

    anni_exp, cats_exp, anni_inc = get_filter_options()
    all_cats = get_all_categories()
    mesi_it = ['', 'Gen', 'Feb', 'Mar', 'Apr', 'Mag', 'Giu', 'Lug', 'Ago', 'Set', 'Ott', 'Nov', 'Dic']

    return render_template('elenco.html',
        expenses=expenses, total_exp=total_exp, page_s=page_s, pages_exp=pages_exp,
        sum_exp=sum_exp, sum_inc=sum_inc,
        incomes=incomes,   total_inc=total_inc, page_e=page_e, pages_inc=pages_inc,
        anni_exp=anni_exp, cats_exp=cats_exp, anni_inc=anni_inc, all_cats=all_cats,
        mesi_it=mesi_it, f_exp=f_exp, f_inc=f_inc,
        active_tab=active_tab, PAGE_SIZE=PAGE_SIZE)


def _csv_safe(text):
    """Un campo di testo che comincia con = + - @ verrebbe eseguito come formula da Excel /
    LibreOffice: lo si neutralizza con un apice (raccomandazione OWASP contro la CSV injection)."""
    text = text or ''
    return "'" + text if text[:1] in ('=', '+', '-', '@', '\t', '\r') else text


@elenco_bp.route('/elenco/export.csv')
def export_csv():
    """Esporta in CSV TUTTE le righe della selezione corrente (non solo la pagina visibile).
    Formato pensato per Excel/LibreOffice in italiano: UTF-8 con BOM, separatore ';',
    virgola come separatore decimale, date ISO."""
    tab = 'entrate' if request.args.get('tab') == 'entrate' else 'spese'
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=';', lineterminator='\r\n')
    money = lambda v: f"{v:.2f}".replace('.', ',')
    if tab == 'spese':
        filters = {k: request.args.get(k, '') for k in ('anno', 'mese', 'cat', 'desc')}
        rows, _, _ = get_expenses(filters, page=None)
        w.writerow(['Data', 'Categoria', 'Tipo', 'Descrizione', 'Importo'])
        for e in rows:
            w.writerow([e['date'], _csv_safe(e['category']),
                        {'essential': 'Necessità', 'extra': 'Extra'}.get(e['type'], ''),
                        _csv_safe(e['description']), money(e['euro'])])
    else:
        filters = {k: request.args.get(k + '_e', '') for k in ('anno', 'mese', 'desc')}
        rows, _, _ = get_incomes_filtered(filters, page=None)
        w.writerow(['Data', 'Descrizione', 'Importo'])
        for i in rows:
            w.writerow([i['date'], _csv_safe(i['description']), money(i['euro'])])
    name = f"{tab}_{datetime.today():%Y-%m-%d}.csv"
    return Response('\ufeff' + buf.getvalue(), mimetype='text/csv',
                    headers={'Content-Disposition': f'attachment; filename="{name}"'})


@elenco_bp.route('/elenco/expense/<int:eid>/edit', methods=['POST'])
def edit_expense(eid):
    date_val    = parse_date(request.form.get('date'))
    euro        = parse_amount(request.form.get('euro'), allow_zero=False)
    description = parse_text(request.form.get('description'))
    with finance_db() as conn:
        category, tipo = category_info(conn, request.form.get('category'))
        # Anche il tipo si aggiorna: segue la categoria (prima restava quello vecchio).
        conn.execute(
            "UPDATE expenses SET date=?, euro=?, category=?, type=?, description=? WHERE id=? AND user_id=1",
            (date_val, euro, category, tipo, description, eid))
        conn.commit()
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return ('', 204)
    flash('Spesa aggiornata.', 'success')
    return redirect(request.referrer or url_for('elenco.index', tab='spese'))


@elenco_bp.route('/elenco/expense/<int:eid>/delete', methods=['POST'])
def delete_expense(eid):
    with finance_db() as conn:
        conn.execute("DELETE FROM expenses WHERE id=? AND user_id=1", (eid,))
        conn.commit()
    flash('Spesa eliminata.', 'success')
    return redirect(request.referrer or url_for('elenco.index', tab='spese'))


@elenco_bp.route('/elenco/income/<int:iid>/edit', methods=['POST'])
def edit_income(iid):
    date_val    = parse_date(request.form.get('date'))
    euro        = parse_amount(request.form.get('euro'), allow_zero=False)
    description = parse_text(request.form.get('description'))
    with finance_db() as conn:
        conn.execute(
            "UPDATE incomes SET date=?, euro=?, description=? WHERE id=? AND user_id=1",
            (date_val, euro, description, iid))
        conn.commit()
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return ('', 204)
    flash('Entrata aggiornata.', 'success')
    return redirect(request.referrer or url_for('elenco.index', tab='entrate'))


@elenco_bp.route('/elenco/income/<int:iid>/delete', methods=['POST'])
def delete_income(iid):
    with finance_db() as conn:
        conn.execute("DELETE FROM incomes WHERE id=? AND user_id=1", (iid,))
        conn.commit()
    flash('Entrata eliminata.', 'success')
    return redirect(request.referrer or url_for('elenco.index', tab='entrate'))
