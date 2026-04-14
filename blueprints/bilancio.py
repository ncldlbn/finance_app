from flask import Blueprint, render_template, request
import json
from datetime import datetime
import calendar
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from db import finance_db
from helpers import q, build_month_range, build_hist_rows, pct, parse_period
from palette import ESSENTIAL, EXTRA

bilancio_bp = Blueprint('bilancio', __name__)


@bilancio_bp.route('/bilancio')
def index():
    today = datetime.today()

    # ---- Tab 1: Riepilogo mensile ----
    anno = int(request.args.get('anno', today.year))
    mese = int(request.args.get('mese', today.month))
    tab  = request.args.get('tab', 'bilancio')

    with finance_db() as conn:
        # Totali mese
        tot_entrate = q(conn, """SELECT COALESCE(SUM(euro),0) FROM incomes
                                 WHERE user_id=1 AND strftime('%Y',date)=? AND strftime('%m',date)=?""",
                        (str(anno), f"{mese:02d}"))[0][0]
        spese_rows = q(conn, """SELECT e.category, e.euro, c.type, e.description, e.date
                                FROM expenses e JOIN category c ON e.category=c.category COLLATE NOCASE
                                WHERE e.user_id=1 AND strftime('%Y',e.date)=? AND strftime('%m',e.date)=?
                                ORDER BY e.date DESC""",
                       (str(anno), f"{mese:02d}"))
        tot_spese     = sum(r[1] for r in spese_rows)
        tot_essential = sum(r[1] for r in spese_rows if r[2] == 'essential')
        tot_extra     = sum(r[1] for r in spese_rows if r[2] == 'extra')
        risparmio     = tot_entrate - tot_spese

        # Categorie per grafico orizzontale
        all_cats = q(conn, "SELECT id, category, type FROM category ORDER BY id")
        from collections import defaultdict
        cat_map    = defaultdict(float)
        detail_map = defaultdict(list)
        for cat, euro, _, desc, date in spese_rows:
            cat_map[cat] += euro
            detail_map[cat].append((date, desc, euro))

        type_map = {r[1]: r[2] for r in all_cats}
        ordered = [r[1] for r in all_cats if r[2] == 'extra'][::-1] + \
                  [r[1] for r in all_cats if r[2] == 'essential'][::-1]

        def fmt_detail(cat):
            items = detail_map.get(cat, [])
            if not items:
                return '(nessuna spesa)'
            return '<br>'.join(f"{d[8:10]}/{d[5:7]}  {desc}  € {euro:.2f}" for d, desc, euro in items)

        chart_bar = json.dumps({
            'x': [cat_map.get(c, 0) for c in ordered],
            'y': ordered,
            'colors': [EXTRA if type_map[c] == 'extra' else ESSENTIAL for c in ordered],
            'details': [fmt_detail(c) for c in ordered],
        })

        # ---- Tab 2: Storico bilancio ----
        period       = request.args.get('period', '12m')
        period_label = {'ytd': 'YTD', '6m': '6 mesi', '12m': '12 mesi',
                        '5y': '5 anni', 'all': "Dall'inizio"}.get(period, '12 mesi')

        start, end = parse_period(period, today)
        if start is None:  # 'all'
            row   = q(conn, """SELECT MIN(date) FROM (
                                   SELECT date FROM incomes WHERE user_id=1
                                   UNION SELECT date FROM expenses WHERE user_id=1)""")
            min_d = row[0][0]
            start = datetime.strptime(min_d, '%Y-%m-%d') if min_d else today

        months   = build_month_range(start, end)
        ss, se   = start.strftime('%Y-%m-%d'), end.strftime('%Y-%m-%d')

        inc_rows = q(conn, """SELECT strftime('%Y',date) y, strftime('%m',date) m, SUM(euro)
                              FROM incomes WHERE user_id=1 AND date BETWEEN ? AND ?
                              GROUP BY y,m ORDER BY y,m""", (ss, se))
        exp_rows = q(conn, """SELECT strftime('%Y',e.date) y, strftime('%m',e.date) m, c.type, SUM(e.euro)
                              FROM expenses e JOIN category c ON e.category=c.category COLLATE NOCASE
                              WHERE e.user_id=1 AND e.date BETWEEN ? AND ?
                              GROUP BY y,m,c.type ORDER BY y,m""", (ss, se))

        inc_map = {f"{r[0]}-{r[1]}": r[2] for r in inc_rows}
        ess_map = {}
        ext_map = {}
        for r in exp_rows:
            k = f"{r[0]}-{r[1]}"
            if r[2] == 'essential':
                ess_map[k] = ess_map.get(k, 0) + r[3]
            else:
                ext_map[k] = ext_map.get(k, 0) + r[3]

        hist_income = [inc_map.get(m, 0) for m in months]
        hist_ess    = [ess_map.get(m, 0) for m in months]
        hist_ext    = [ext_map.get(m, 0) for m in months]

        hist_rows, hist_savings, totals = build_hist_rows(months, hist_income, hist_ess, hist_ext)

        chart_hist = json.dumps({
            'labels':    months,
            'essential': hist_ess,
            'extra':     hist_ext,
            'savings':   hist_savings,
            'income':    hist_income,
        })

        # ---- Tab 3: Confronto annuale ----
        years_available = sorted(set(r[0] for r in q(conn, """
            SELECT DISTINCT strftime('%Y',date) FROM (
                SELECT date FROM incomes WHERE user_id=1
                UNION SELECT date FROM expenses WHERE user_id=1)""")), reverse=True)

        yearly = []
        for yr in years_available:
            inc = q(conn, "SELECT COALESCE(SUM(euro),0) FROM incomes WHERE user_id=1 AND strftime('%Y',date)=?", (yr,))[0][0]
            exp = q(conn, "SELECT COALESCE(SUM(euro),0) FROM expenses WHERE user_id=1 AND strftime('%Y',date)=?", (yr,))[0][0]
            yearly.append({'year': yr, 'income': inc, 'expense': exp, 'savings': inc - exp})

        # ---- Categorie annuali ----
        ann_entrate = q(conn, """SELECT COALESCE(SUM(euro),0) FROM incomes
                                 WHERE user_id=1 AND strftime('%Y',date)=?""",
                        (str(anno),))[0][0]
        ann_spese_rows = q(conn, """SELECT e.category, e.euro, e.description, e.date
                                    FROM expenses e JOIN category c ON e.category=c.category COLLATE NOCASE
                                    WHERE e.user_id=1 AND strftime('%Y',e.date)=?
                                    ORDER BY e.date DESC""",
                           (str(anno),))

    ann_tot_spese     = sum(r[1] for r in ann_spese_rows)
    ann_tot_essential = sum(r[1] for r in ann_spese_rows if type_map.get(r[0]) == 'essential')
    ann_tot_extra     = sum(r[1] for r in ann_spese_rows if type_map.get(r[0]) == 'extra')
    ann_risparmio     = ann_entrate - ann_tot_spese

    ann_cat_map    = defaultdict(float)
    ann_detail_map = defaultdict(list)
    for cat, euro, desc, date in ann_spese_rows:
        ann_cat_map[cat] += euro
        ann_detail_map[cat].append((date, desc, euro))

    def fmt_detail_ann(cat):
        items = ann_detail_map.get(cat, [])
        if not items:
            return '(nessuna spesa)'
        return '<br>'.join(f"{d[8:10]}/{d[5:7]}  {desc}  € {euro:.2f}" for d, desc, euro in items)

    chart_bar_ann = json.dumps({
        'x': [ann_cat_map.get(c, 0) for c in ordered],
        'y': ordered,
        'colors': [EXTRA if type_map[c] == 'extra' else ESSENTIAL for c in ordered],
        'details': [fmt_detail_ann(c) for c in ordered],
    })

    mesi_it    = ['', 'Gennaio', 'Febbraio', 'Marzo', 'Aprile', 'Maggio', 'Giugno',
                  'Luglio', 'Agosto', 'Settembre', 'Ottobre', 'Novembre', 'Dicembre']
    anni_range = [int(y) for y in years_available]

    return render_template('bilancio.html',
        anno=anno, mese=mese, tab=tab,
        tot_entrate=tot_entrate, tot_spese=tot_spese, risparmio=risparmio,
        tot_essential=tot_essential, tot_extra=tot_extra,
        chart_bar=chart_bar,
        period=period, period_label=period_label,
        chart_hist=chart_hist,
        tot_inc_p=totals['tot_inc'], tot_exp_p=totals['tot_exp'], tot_sav_p=totals['tot_sav'],
        avg_inc=totals['avg_inc'], avg_exp=totals['avg_exp'], avg_sav=totals['avg_sav'], nm=totals['nm'],
        tot_ess_p=totals['tot_ess'], tot_ext_p=totals['tot_ext'],
        hist_rows=hist_rows,
        yearly=yearly,
        ann_entrate=ann_entrate,
        ann_tot_spese=ann_tot_spese, ann_risparmio=ann_risparmio,
        ann_tot_essential=ann_tot_essential, ann_tot_extra=ann_tot_extra,
        chart_bar_ann=chart_bar_ann,
        mesi_it=mesi_it, anni_range=anni_range,
        years_available=years_available,
    )
