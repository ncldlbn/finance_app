from flask import Blueprint, render_template, request, flash, redirect, url_for
import sqlite3, sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from db import get_finance_conn

elenco_bp = Blueprint('elenco', __name__)
PAGE_SIZE = 50

def get_expenses(filters=None, page=1):
    conn = get_finance_conn()
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

    total = conn.execute("SELECT COUNT(*) FROM (" + base + ")", params).fetchone()[0]
    base += " ORDER BY e.date DESC, e.rowid DESC LIMIT ? OFFSET ?"
    rows = conn.execute(base, params + [PAGE_SIZE, (page-1)*PAGE_SIZE]).fetchall()
    conn.close()

    expenses = [dict(id=r[0], date=r[1], euro=r[2], category=r[3], description=r[4] or '', type=r[5])
                for r in rows]
    return expenses, total

def get_incomes_filtered(filters=None, page=1):
    conn = get_finance_conn()
    base = "SELECT id, date, euro, description FROM incomes WHERE user_id=1"
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

    total = conn.execute("SELECT COUNT(*) FROM (" + base + ")", params).fetchone()[0]
    base += " ORDER BY date DESC, rowid DESC LIMIT ? OFFSET ?"
    rows = conn.execute(base, params + [PAGE_SIZE, (page-1)*PAGE_SIZE]).fetchall()
    conn.close()
    incomes = [dict(id=r[0], date=r[1], euro=r[2], description=r[3] or '') for r in rows]
    return incomes, total

def get_filter_options():
    conn = get_finance_conn()
    anni_exp = [r[0] for r in conn.execute(
        "SELECT DISTINCT strftime('%Y',date) y FROM expenses WHERE user_id=1 ORDER BY y DESC").fetchall()]
    cats_exp = [r[0] for r in conn.execute(
        "SELECT DISTINCT category FROM expenses WHERE user_id=1 ORDER BY category").fetchall()]
    anni_inc = [r[0] for r in conn.execute(
        "SELECT DISTINCT strftime('%Y',date) y FROM incomes WHERE user_id=1 ORDER BY y DESC").fetchall()]
    conn.close()
    return anni_exp, cats_exp, anni_inc

@elenco_bp.route('/elenco')
def index():
    active_tab = request.args.get('tab', 'spese')

    # Expense filters
    f_exp = {k: request.args.get(k, '') for k in ('anno', 'mese', 'cat', 'desc')}
    page_s = int(request.args.get('page_s', 1))
    expenses, total_exp = get_expenses(f_exp, page_s)
    pages_exp = max(1, (total_exp + PAGE_SIZE - 1) // PAGE_SIZE)

    # Income filters
    f_inc = {k: request.args.get(k+'_e', '') for k in ('anno', 'mese', 'desc')}
    page_e = int(request.args.get('page_e', 1))
    incomes, total_inc = get_incomes_filtered(f_inc, page_e)
    pages_inc = max(1, (total_inc + PAGE_SIZE - 1) // PAGE_SIZE)

    anni_exp, cats_exp, anni_inc = get_filter_options()
    mesi_it = ['','Gen','Feb','Mar','Apr','Mag','Giu','Lug','Ago','Set','Ott','Nov','Dic']

    return render_template('elenco.html',
        expenses=expenses, total_exp=total_exp, page_s=page_s, pages_exp=pages_exp,
        incomes=incomes,  total_inc=total_inc, page_e=page_e, pages_inc=pages_inc,
        anni_exp=anni_exp, cats_exp=cats_exp, anni_inc=anni_inc,
        mesi_it=mesi_it, f_exp=f_exp, f_inc=f_inc,
        active_tab=active_tab, PAGE_SIZE=PAGE_SIZE)

@elenco_bp.route('/elenco/expense/<int:eid>/edit', methods=['POST'])
def edit_expense(eid):
    conn = get_finance_conn()
    conn.execute("UPDATE expenses SET date=?, euro=?, category=?, description=? WHERE id=? AND user_id=1",
                 (request.form['date'], float(request.form['euro'].replace(',','.')),
                  request.form['category'], request.form.get('description',''), eid))
    conn.commit(); conn.close()
    flash('Spesa aggiornata.', 'success')
    return redirect(request.referrer or url_for('elenco.index', tab='spese'))

@elenco_bp.route('/elenco/expense/<int:eid>/delete', methods=['POST'])
def delete_expense(eid):
    conn = get_finance_conn()
    conn.execute("DELETE FROM expenses WHERE id=? AND user_id=1", (eid,))
    conn.commit(); conn.close()
    flash('Spesa eliminata.', 'success')
    return redirect(request.referrer or url_for('elenco.index', tab='spese'))

@elenco_bp.route('/elenco/income/<int:iid>/edit', methods=['POST'])
def edit_income(iid):
    conn = get_finance_conn()
    conn.execute("UPDATE incomes SET date=?, euro=?, description=? WHERE id=? AND user_id=1",
                 (request.form['date'], float(request.form['euro'].replace(',','.')),
                  request.form.get('description',''), iid))
    conn.commit(); conn.close()
    flash('Entrata aggiornata.', 'success')
    return redirect(request.referrer or url_for('elenco.index', tab='entrate'))

@elenco_bp.route('/elenco/income/<int:iid>/delete', methods=['POST'])
def delete_income(iid):
    conn = get_finance_conn()
    conn.execute("DELETE FROM incomes WHERE id=? AND user_id=1", (iid,))
    conn.commit(); conn.close()
    flash('Entrata eliminata.', 'success')
    return redirect(request.referrer or url_for('elenco.index', tab='entrate'))
