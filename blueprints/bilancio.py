from flask import Blueprint, render_template, request
import sqlite3, json, sys, os
from datetime import datetime, timedelta
import calendar
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from db import get_finance_conn

bilancio_bp = Blueprint('bilancio', __name__)

def q(conn, sql, params=()):
    cur = conn.execute(sql, params)
    return cur.fetchall()

@bilancio_bp.route('/bilancio')
def index():
    today = datetime.today()
    conn  = get_finance_conn()

    # ---- Tab 1: Riepilogo mensile ----
    anno  = int(request.args.get('anno',  today.year))
    mese  = int(request.args.get('mese',  today.month))
    tab   = request.args.get('tab', 'bilancio')

    # Totali mese
    tot_entrate = q(conn, """SELECT COALESCE(SUM(euro),0) FROM incomes
                             WHERE user_id=1 AND strftime('%Y',date)=? AND strftime('%m',date)=?""",
                    (str(anno), f"{mese:02d}"))[0][0]
    spese_rows  = q(conn, """SELECT e.category, e.euro, c.type, e.description, e.date
                             FROM expenses e JOIN category c ON e.category=c.category COLLATE NOCASE
                             WHERE e.user_id=1 AND strftime('%Y',e.date)=? AND strftime('%m',e.date)=?
                             ORDER BY e.date DESC""",
                    (str(anno), f"{mese:02d}"))
    tot_spese     = sum(r[1] for r in spese_rows)
    tot_essential = sum(r[1] for r in spese_rows if r[2] == 'essential')
    tot_extra     = sum(r[1] for r in spese_rows if r[2] == 'extra')
    risparmio     = tot_entrate - tot_spese

    # Spese per categoria (grafico orizzontale)
    all_cats = q(conn, "SELECT id, category, type FROM category ORDER BY id")
    from collections import defaultdict
    cat_map    = defaultdict(float)
    detail_map = defaultdict(list)   # {cat: [(date, desc, euro), ...]}
    for cat, euro, _, desc, date in spese_rows:
        cat_map[cat] += euro
        detail_map[cat].append((date, desc, euro))

    type_map = {r[1]: r[2] for r in all_cats}
    # extra in fondo (bottom), essential in cima (top) nel grafico h
    # inversione interna: ultimo elemento = più in alto → Casa in cima
    ordered = [r[1] for r in all_cats if r[2] == 'extra'][::-1] + \
              [r[1] for r in all_cats if r[2] == 'essential'][::-1]
    bar_cats   = ordered
    bar_values = [cat_map.get(c, 0) for c in bar_cats]
    bar_colors = ['#ff7f0e' if type_map[c] == 'extra' else '#1f77b4' for c in bar_cats]

    def fmt_detail(cat):
        items = detail_map.get(cat, [])
        if not items:
            return '(nessuna spesa)'
        lines = [f"{d[8:10]}/{d[5:7]}  {desc}  € {euro:.2f}"
                 for d, desc, euro in items]
        return '<br>'.join(lines)

    bar_details = [fmt_detail(c) for c in bar_cats]

    chart_bar = json.dumps({
        'x': bar_values, 'y': bar_cats,
        'colors': bar_colors, 'details': bar_details
    })

    # ---- Tab 2: Storico bilancio ----
    period = request.args.get('period', '12m')
    period_label = {'ytd':'YTD','6m':'6 mesi','12m':'12 mesi','5y':'5 anni','all':'Dall\'inizio'}.get(period,'12 mesi')

    if period == 'ytd':
        start = datetime(today.year, 1, 1)
    elif period == '6m':
        start = (today.replace(day=1) - timedelta(days=1)).replace(day=1)
        for _ in range(5):
            start = (start - timedelta(days=1)).replace(day=1)
    elif period == '12m':
        m = today.month - 11
        y = today.year
        if m <= 0: m += 12; y -= 1
        start = datetime(y, m, 1)
    elif period == '5y':
        start = datetime(today.year - 4, 1, 1)
    else:  # all
        row = q(conn, """SELECT MIN(date) FROM (
                            SELECT date FROM incomes WHERE user_id=1
                            UNION SELECT date FROM expenses WHERE user_id=1)""")
        min_d = row[0][0]
        start = datetime.strptime(min_d, '%Y-%m-%d') if min_d else today

    last_day = calendar.monthrange(today.year, today.month)[1]
    end = today.replace(day=last_day)
    start_str = start.strftime('%Y-%m-%d')
    end_str   = end.strftime('%Y-%m-%d')

    inc_rows = q(conn, """SELECT strftime('%Y',date) y, strftime('%m',date) m, SUM(euro)
                          FROM incomes WHERE user_id=1 AND date BETWEEN ? AND ?
                          GROUP BY y,m ORDER BY y,m""", (start_str, end_str))
    exp_rows = q(conn, """SELECT strftime('%Y',e.date) y, strftime('%m',e.date) m, c.type, SUM(e.euro)
                          FROM expenses e JOIN category c ON e.category=c.category COLLATE NOCASE
                          WHERE e.user_id=1 AND e.date BETWEEN ? AND ?
                          GROUP BY y,m,c.type ORDER BY y,m""", (start_str, end_str))

    # Build month range
    months = []
    cur_m = start.replace(day=1)
    while cur_m <= end.replace(day=1):
        months.append(f"{cur_m.year}-{cur_m.month:02d}")
        if cur_m.month == 12:
            cur_m = cur_m.replace(year=cur_m.year+1, month=1)
        else:
            cur_m = cur_m.replace(month=cur_m.month+1)

    inc_map  = {f"{r[0]}-{r[1]}": r[2] for r in inc_rows}
    ess_map  = {}; ext_map = {}
    for r in exp_rows:
        k = f"{r[0]}-{r[1]}"
        if r[2] == 'essential': ess_map[k] = ess_map.get(k,0) + r[3]
        else:                   ext_map[k] = ext_map.get(k,0) + r[3]

    hist_labels  = months
    hist_income  = [inc_map.get(m, 0) for m in months]
    hist_ess     = [ess_map.get(m, 0) for m in months]
    hist_ext     = [ext_map.get(m, 0) for m in months]
    hist_savings = [hist_income[i] - hist_ess[i] - hist_ext[i] for i in range(len(months))]

    # Stats for the period
    tot_inc_p  = sum(hist_income)
    tot_ess_p  = sum(hist_ess)
    tot_ext_p  = sum(hist_ext)
    tot_exp_p  = tot_ess_p + tot_ext_p
    tot_sav_p  = sum(hist_savings)
    nm         = len(months) or 1
    avg_inc    = tot_inc_p / nm
    avg_exp    = tot_exp_p / nm
    avg_sav    = tot_sav_p / nm

    chart_hist = json.dumps({
        'labels': hist_labels,
        'essential': hist_ess,
        'extra': hist_ext,
        'savings': hist_savings,
        'income': hist_income,
    })

    def pct(val, base):
        return val / base * 100 if base else 0

    def rule_status(p_ess, p_ext, p_sav):
        """green/yellow/red secondo regola 50/30/20."""
        if p_ess <= 50 and p_ext <= 30 and p_sav >= 20:
            return 'green'
        if p_ess <= 60 and p_ext <= 40 and p_sav >= 10:
            return 'yellow'
        return 'red'

    hist_rows = []
    for i, m in enumerate(months):
        inc  = hist_income[i]
        ess  = hist_ess[i]
        ext  = hist_ext[i]
        exp  = ess + ext
        sav  = hist_savings[i]
        p_ess = pct(ess, inc)
        p_ext = pct(ext, inc)
        p_sav = pct(sav, inc)
        hist_rows.append({
            'label':   m,
            'inc':     inc,
            'exp':     exp,
            'ess':     ess,
            'ext':     ext,
            'sav':     sav,
            'pct_exp': pct(exp, inc),
            'pct_ess': p_ess,
            'pct_ext': p_ext,
            'pct_sav': p_sav,
            'status':  rule_status(p_ess, p_ext, p_sav) if inc > 0 else None,
        })
    # Riga totale
    tp_ess = pct(tot_ess_p, tot_inc_p)
    tp_ext = pct(tot_ext_p, tot_inc_p)
    tp_sav = pct(tot_sav_p, tot_inc_p)
    hist_rows.append({
        'label':   'Totale',
        'inc':     tot_inc_p,
        'exp':     tot_exp_p,
        'ess':     tot_ess_p,
        'ext':     tot_ext_p,
        'sav':     tot_sav_p,
        'pct_exp': pct(tot_exp_p, tot_inc_p),
        'pct_ess': tp_ess,
        'pct_ext': tp_ext,
        'pct_sav': tp_sav,
        'status':  rule_status(tp_ess, tp_ext, tp_sav) if tot_inc_p > 0 else None,
        'is_total': True,
    })

    # ---- Tab 3: Confronto annuale ----
    cur_year = today.year
    years_available = sorted(set(r[0] for r in q(conn, """
        SELECT DISTINCT strftime('%Y',date) FROM (
            SELECT date FROM incomes WHERE user_id=1
            UNION SELECT date FROM expenses WHERE user_id=1)""")), reverse=True)

    yearly = []
    for yr in years_available:
        inc = q(conn, "SELECT COALESCE(SUM(euro),0) FROM incomes WHERE user_id=1 AND strftime('%Y',date)=?", (yr,))[0][0]
        exp = q(conn, "SELECT COALESCE(SUM(euro),0) FROM expenses WHERE user_id=1 AND strftime('%Y',date)=?", (yr,))[0][0]
        yearly.append({'year': yr, 'income': inc, 'expense': exp, 'savings': inc - exp})

    # ---- Categorie annuali (stesso anno del mensile) ----
    ann_entrate = q(conn, """SELECT COALESCE(SUM(euro),0) FROM incomes
                             WHERE user_id=1 AND strftime('%Y',date)=?""",
                    (str(anno),))[0][0]
    ann_spese_rows = q(conn, """SELECT e.category, e.euro, e.description, e.date
                                FROM expenses e JOIN category c ON e.category=c.category COLLATE NOCASE
                                WHERE e.user_id=1 AND strftime('%Y',e.date)=?
                                ORDER BY e.date DESC""",
                       (str(anno),))
    ann_tot_spese      = sum(r[1] for r in ann_spese_rows)
    ann_tot_essential  = sum(r[1] for r in ann_spese_rows if type_map.get(r[0]) == 'essential')
    ann_tot_extra      = sum(r[1] for r in ann_spese_rows if type_map.get(r[0]) == 'extra')
    ann_risparmio      = ann_entrate - ann_tot_spese

    ann_cat_map    = defaultdict(float)
    ann_detail_map = defaultdict(list)
    for cat, euro, desc, date in ann_spese_rows:
        ann_cat_map[cat] += euro
        ann_detail_map[cat].append((date, desc, euro))

    ann_bar_cats   = ordered   # stesso ordine del grafico mensile
    ann_bar_values = [ann_cat_map.get(c, 0) for c in ann_bar_cats]
    ann_bar_colors = ['#ff7f0e' if type_map[c] == 'extra' else '#1f77b4' for c in ann_bar_cats]

    def fmt_detail_ann(cat):
        items = ann_detail_map.get(cat, [])
        if not items:
            return '(nessuna spesa)'
        lines = [f"{d[8:10]}/{d[5:7]}  {desc}  € {euro:.2f}"
                 for d, desc, euro in items]
        return '<br>'.join(lines)

    ann_bar_details = [fmt_detail_ann(c) for c in ann_bar_cats]

    chart_bar_ann = json.dumps({
        'x': ann_bar_values, 'y': ann_bar_cats,
        'colors': ann_bar_colors, 'details': ann_bar_details
    })

    conn.close()

    mesi_it = ['','Gennaio','Febbraio','Marzo','Aprile','Maggio','Giugno',
               'Luglio','Agosto','Settembre','Ottobre','Novembre','Dicembre']
    anni_range = [int(y) for y in years_available]

    return render_template('bilancio.html',
        anno=anno, mese=mese, tab=tab,
        tot_entrate=tot_entrate, tot_spese=tot_spese, risparmio=risparmio,
        tot_essential=tot_essential, tot_extra=tot_extra,
        chart_bar=chart_bar,
        period=period, period_label=period_label,
        chart_hist=chart_hist,
        tot_inc_p=tot_inc_p, tot_exp_p=tot_exp_p, tot_sav_p=tot_sav_p,
        avg_inc=avg_inc, avg_exp=avg_exp, avg_sav=avg_sav, nm=nm,
        tot_ess_p=tot_ess_p, tot_ext_p=tot_ext_p,
        hist_rows=hist_rows,
        yearly=yearly,
        ann_entrate=ann_entrate,
        ann_tot_spese=ann_tot_spese, ann_risparmio=ann_risparmio,
        ann_tot_essential=ann_tot_essential, ann_tot_extra=ann_tot_extra,
        chart_bar_ann=chart_bar_ann,
        mesi_it=mesi_it, anni_range=anni_range,
        years_available=years_available,
    )
