from flask import Blueprint, render_template, request
import json, statistics, sys, os
from datetime import datetime, timedelta
from collections import defaultdict
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from db import finance_db
from helpers import (q, build_month_range, build_monthly_maps,
                     build_hist_rows, pct, rule_status, parse_period, compute_budget)
from palette import YEAR_PALETTE, ESSENTIAL, EXTRA, INCOME, EXPENSE, SAVINGS, SANKEY, PLOT

statistiche_bp = Blueprint('statistiche', __name__)
MESI_IT = ['Gen', 'Feb', 'Mar', 'Apr', 'Mag', 'Giu', 'Lug', 'Ago', 'Set', 'Ott', 'Nov', 'Dic']


@statistiche_bp.route('/statistiche')
def index():
    today = datetime.today()
    tab   = request.args.get('tab', 'bil_mensile')

    with finance_db() as conn:
        # ── Anni disponibili ────────────────────────────────────────────
        all_years = sorted(set(
            r[0] for r in q(conn, """
                SELECT DISTINCT strftime('%Y',date) FROM (
                    SELECT date FROM incomes WHERE user_id=1
                    UNION SELECT date FROM expenses WHERE user_id=1)
            """)
        ))
        sel_year = request.args.get('year', str(today.year))
        if sel_year not in all_years:
            sel_year = all_years[-1] if all_years else str(today.year)

        # ── Dati spese con tipo/categoria ───────────────────────────────
        exp_rows = q(conn, """
            SELECT strftime('%Y',e.date) y, strftime('%m',e.date) m,
                   CAST(julianday(e.date)-julianday(strftime('%Y',e.date)||'-01-01')+1 AS INTEGER) doy,
                   e.euro, e.category, c.type
            FROM expenses e JOIN category c ON e.category=c.category
            WHERE e.user_id=1
        """)

        if not exp_rows:
            return render_template('statistiche.html', empty=True)

        all_cats    = sorted(set(r[4] for r in exp_rows))
        years_av    = sorted(set(int(r[0]) for r in exp_rows))
        cat_sel     = request.args.get('categoria', 'Totale')
        anni_sel    = [int(a) for a in request.args.getlist('anni')] or years_av[-3:]
        cat_options = ['Totale', 'Totale necessità', 'Totale extra'] + all_cats

        def filter_rows(rs, cat):
            if cat == 'Totale':           return rs
            if cat == 'Totale necessità': return [r for r in rs if r[5] == 'essential']
            if cat == 'Totale extra':     return [r for r in rs if r[5] == 'extra']
            return [r for r in rs if r[4] == cat]

        frows  = filter_rows(exp_rows, cat_sel)
        COLORS = YEAR_PALETTE

        # ── Tab 1: Spese per anno/cat ───────────────────────────────────
        stats = []
        for i, yr in enumerate(sorted(anni_sel)):
            yr_rows = [r for r in frows if int(r[0]) == yr]
            total   = sum(r[3] for r in yr_rows)
            mths    = today.month if yr == today.year else 12
            avg_m   = total / mths if mths else 0
            m_tot = {}
            for r in yr_rows:
                m_tot[int(r[1])] = m_tot.get(int(r[1]), 0) + r[3]
            # Solo mesi con almeno una spesa
            active = {m: v for m, v in m_tot.items() if v > 0}
            if active:
                mx = max(active, key=active.get)
                mn = min(active, key=active.get)
                min_info = f"€{active[mn]:,.0f} ({MESI_IT[mn-1].lower()})"
                max_info = f"€{active[mx]:,.0f} ({MESI_IT[mx-1].lower()})"
                std_dev = statistics.pstdev(list(active.values())) if len(active) > 1 else 0
            else:
                min_info = max_info = 'N/D'
                std_dev = 0
            delta_str = '–'
            if i > 0:
                prev_yr   = sorted(anni_sel)[i - 1]
                prev_rows = [r for r in frows if int(r[0]) == prev_yr]
                prev_tot  = sum(r[3] for r in prev_rows)
                prev_mths = today.month if prev_yr == today.year else 12
                prev_avg  = prev_tot / prev_mths if prev_mths else 0
                delta_str = f"{((avg_m - prev_avg) / prev_avg * 100):+.1f}%" if prev_avg else 'N/D'
            stats.append({'anno': yr, 'totale': total, 'media': avg_m,
                          'std': std_dev, 'min': min_info, 'max': max_info, 'delta': delta_str})

        cum_series, monthly_series = [], []
        for i, yr in enumerate(sorted(anni_sel)):
            yr_rows = sorted([r for r in frows if int(r[0]) == yr], key=lambda r: r[2])
            doy_map = {}
            for r in yr_rows:
                doy_map[r[2]] = doy_map.get(r[2], 0) + r[3]
            days = sorted(doy_map.keys())
            cumul = 0
            xs, ys, xlabels = [], [], []
            for d in days:
                cumul += doy_map[d]
                xs.append(d)
                ys.append(round(cumul, 2))
                # Converti doy in data leggibile DD/MM
                actual = datetime(yr, 1, 1) + timedelta(days=d - 1)
                xlabels.append(actual.strftime('%d/%m'))
            cum_series.append({'year': str(yr), 'x': xs, 'y': ys,
                               'labels': xlabels, 'color': COLORS[i % len(COLORS)]})
            m_tot = {m: 0 for m in range(1, 13)}
            for r in yr_rows:
                m_tot[int(r[1])] += r[3]
            monthly_series.append({'year': str(yr), 'values': [round(m_tot[m], 2) for m in range(1, 13)],
                                    'color': COLORS[i % len(COLORS)]})

        # ── Tab 2: Saving Rate ──────────────────────────────────────────
        sr_year = request.args.get('sr_year', '')
        inc_map_sr, spe_map_sr = build_monthly_maps(conn, sr_year if sr_year else None)
        all_months_sr = sorted(set(list(inc_map_sr.keys()) + list(spe_map_sr.keys())))
        sr_labels, sr_rates, sr_inc, sr_spe, sr_sav = [], [], [], [], []
        for ym in all_months_sr:
            inc  = inc_map_sr.get(ym, 0)
            spe  = spe_map_sr.get(ym, 0)
            sav  = inc - spe
            rate = (sav / inc * 100) if inc > 0 else 0
            sr_labels.append(ym)
            sr_rates.append(round(rate, 1))
            sr_inc.append(round(inc, 2))
            sr_spe.append(round(spe, 2))
            sr_sav.append(round(sav, 2))
        recent_rates  = [r for r in sr_rates if r != 0][-12:]
        avg_sr        = round(sum(recent_rates) / len(recent_rates), 1) if recent_rates else 0
        saving_rate_data = json.dumps({'labels': sr_labels, 'rates': sr_rates,
                                       'income': sr_inc, 'spese': sr_spe, 'savings': sr_sav})

        # ── Tab 3: Proiezione ───────────────────────────────────────────
        proj_year = int(request.args.get('proj_year', today.year))
        inc_map_p, spe_map_p = build_monthly_maps(conn, str(proj_year))
        months_done_p = [f"{proj_year}-{m:02d}" for m in range(1, (today.month if proj_year == today.year else 13))]
        proj_months_remaining = 12 - today.month + 1 if proj_year == today.year else 0
        ref_p = months_done_p[-3:] if len(months_done_p) >= 3 else months_done_p
        avg_inc_proj = sum(inc_map_p.get(m, 0) for m in ref_p) / len(ref_p) if ref_p else 0
        avg_spe_proj = sum(spe_map_p.get(m, 0) for m in ref_p) / len(ref_p) if ref_p else 0
        ytd_inc = sum(inc_map_p.get(f"{proj_year}-{m:02d}", 0) for m in range(1, 13))
        ytd_spe = sum(spe_map_p.get(f"{proj_year}-{m:02d}", 0) for m in range(1, 13))
        proj_inc = ytd_inc + avg_inc_proj * proj_months_remaining
        proj_spe = ytd_spe + avg_spe_proj * proj_months_remaining
        proj_sav = proj_inc - proj_spe
        ytd_sav  = ytd_inc - ytd_spe

        # ── Tab 4: Nec vs Extra ─────────────────────────────────────────
        ne_year = request.args.get('ne_year', '')
        ne_params = (ne_year,) if ne_year else ()
        ne_where  = "AND strftime('%Y',e.date)=?" if ne_year else ""
        nec_ext_rows = q(conn, f"""
            SELECT strftime('%Y',e.date) y, strftime('%m',e.date) m, c.type, SUM(e.euro)
            FROM expenses e JOIN category c ON e.category=c.category
            WHERE e.user_id=1 {ne_where} GROUP BY y,m,c.type ORDER BY y,m
        """, ne_params)
        nec_map2 = {}
        ext_map2 = {}
        for r in nec_ext_rows:
            k = f"{r[0]}-{r[1]}"
            if r[2] == 'essential':
                nec_map2[k] = r[3]
            else:
                ext_map2[k] = r[3]
        ne_months = sorted(set(list(nec_map2.keys()) + list(ext_map2.keys())))
        ne_nec = [round(nec_map2.get(m, 0), 2) for m in ne_months]
        ne_ext = [round(ext_map2.get(m, 0), 2) for m in ne_months]
        ne_pct = [round(ext_map2.get(m, 0) / (nec_map2.get(m, 0) + ext_map2.get(m, 0)) * 100, 1)
                  if (nec_map2.get(m, 0) + ext_map2.get(m, 0)) > 0 else 0
                  for m in ne_months]
        nec_ext_data = json.dumps({'labels': ne_months, 'nec': ne_nec, 'ext': ne_ext, 'pct_ext': ne_pct})

        # ── Tab 5: Anomalie ─────────────────────────────────────────────
        anom_year = request.args.get('anom_year', '')
        inc_map_a, spe_map_a = build_monthly_maps(conn, anom_year if anom_year else None)
        all_months_a = sorted(set(list(inc_map_a.keys()) + list(spe_map_a.keys())))
        spe_vals_a = [spe_map_a[m] for m in all_months_a if m in spe_map_a]
        anomaly_threshold = None
        anomalies = []
        if len(spe_vals_a) >= 3:
            avg_s = statistics.mean(spe_vals_a)
            std_s = statistics.stdev(spe_vals_a)
            anomaly_threshold = avg_s + std_s
            for ym in all_months_a:
                s = spe_map_a.get(ym, 0)
                if s > anomaly_threshold:
                    anomalies.append({'mese': ym, 'spesa': s,
                                      'delta': s - avg_s, 'delta_pct': (s - avg_s) / avg_s * 100})
            anomalies.sort(key=lambda x: -x['spesa'])

        # ── Tab 6: Frequenza ────────────────────────────────────────────
        freq_year = request.args.get('freq_year', str(today.year))
        freq_rows = q(conn, """
            SELECT category, COUNT(*) cnt, SUM(euro) tot, AVG(euro) avg_e
            FROM expenses WHERE user_id=1 AND strftime('%Y',date)=?
            GROUP BY category ORDER BY cnt DESC
        """, (freq_year,))
        freq_data = [{'cat': r[0], 'cnt': r[1], 'tot': round(r[2], 2), 'avg': round(r[3], 2)}
                     for r in freq_rows]

        # ── Tab 7: Sankey ───────────────────────────────────────────────
        sank_year      = request.args.get('sank_year', str(today.year))
        total_inc_sank = q(conn,
            "SELECT COALESCE(SUM(euro),0) FROM incomes WHERE user_id=1 AND strftime('%Y',date)=?",
            (sank_year,))[0][0]
        cat_rows_sank  = q(conn, """
            SELECT e.category, c.type, SUM(e.euro)
            FROM expenses e JOIN category c ON e.category=c.category
            WHERE e.user_id=1 AND strftime('%Y',e.date)=?
            GROUP BY e.category, c.type ORDER BY 3 DESC
        """, (sank_year,))

        total_spe_sank = sum(r[2] for r in cat_rows_sank)
        risparmio_sank = total_inc_sank - total_spe_sank
        nec_sank = sum(r[2] for r in cat_rows_sank if r[1] == 'essential')
        ext_sank = sum(r[2] for r in cat_rows_sank if r[1] == 'extra')

        san_nodes       = ['Entrate', 'Risparmio', 'Spese totali', 'Necessità', 'Extra']
        san_sources, san_targets, san_values, san_colors_link = [], [], [], []
        node_colors     = [INCOME, SAVINGS, EXPENSE, ESSENTIAL, EXTRA]
        cat_color_map   = {'essential': SANKEY['link_cat_ess'], 'extra': SANKEY['link_cat_ext']}

        if risparmio_sank > 0:
            san_sources.append(0); san_targets.append(1); san_values.append(round(risparmio_sank, 2))
            san_colors_link.append(SANKEY['link_savings'])
        san_sources.append(0); san_targets.append(2); san_values.append(round(total_spe_sank, 2))
        san_colors_link.append(SANKEY['link_expense'])
        if nec_sank > 0:
            san_sources.append(2); san_targets.append(3); san_values.append(round(nec_sank, 2))
            san_colors_link.append(SANKEY['link_essential'])
        if ext_sank > 0:
            san_sources.append(2); san_targets.append(4); san_values.append(round(ext_sank, 2))
            san_colors_link.append(SANKEY['link_extra'])
        for r in cat_rows_sank:
            if r[2] < 1:
                continue
            idx = len(san_nodes)
            san_nodes.append(r[0])
            node_colors.append(SANKEY['node_cat'])
            parent_idx = 3 if r[1] == 'essential' else 4
            san_sources.append(parent_idx); san_targets.append(idx); san_values.append(round(r[2], 2))
            san_colors_link.append(cat_color_map.get(r[1], 'rgba(124,131,245,0.25)'))

        sankey_data = json.dumps({
            'nodes': san_nodes, 'node_colors': node_colors,
            'sources': san_sources, 'targets': san_targets,
            'values': san_values, 'link_colors': san_colors_link,
        })

        # ── Tab Bilancio mensile/annuale ────────────────────────────────
        mesi_it_full = ['', 'Gennaio', 'Febbraio', 'Marzo', 'Aprile', 'Maggio', 'Giugno',
                        'Luglio', 'Agosto', 'Settembre', 'Ottobre', 'Novembre', 'Dicembre']
        bil_anno = int(request.args.get('anno', today.year))
        bil_mese = int(request.args.get('mese', today.month))
        bil_anni_range = [int(y) for y in all_years]

        all_cats_ordered = q(conn, "SELECT id, category, type FROM category ORDER BY id")
        type_map_bil  = {r[1]: r[2] for r in all_cats_ordered}
        ordered_cats  = [r[1] for r in all_cats_ordered if r[2] == 'extra'][::-1] + \
                        [r[1] for r in all_cats_ordered if r[2] == 'essential'][::-1]

        def build_bar_chart(rows, cat_list, tmap):
            cat_m = defaultdict(float)
            det_m = defaultdict(list)
            for cat, euro, desc, date in rows:
                cat_m[cat] += euro
                det_m[cat].append((date, desc, euro))
            vals   = [cat_m.get(c, 0) for c in cat_list]
            colors = [EXTRA if tmap[c] == 'extra' else ESSENTIAL for c in cat_list]
            def fmt(cat):
                items = det_m.get(cat, [])
                if not items:
                    return '(nessuna spesa)'
                return '<br>'.join(f"{d[8:10]}/{d[5:7]}  {desc}  € {euro:.2f}" for d, desc, euro in items)
            return json.dumps({'x': vals, 'y': cat_list, 'colors': colors, 'details': [fmt(c) for c in cat_list]})

        def build_cat_list(rows, all_cats):
            cat_m = defaultdict(float)
            cat_det = defaultdict(list)
            for cat, euro, desc, date in rows:
                cat_m[cat] += euro
                cat_det[cat].append((date, desc, euro))
            result = []
            for group_type in ('essential', 'extra'):
                group = [(r[1], r[2]) for r in all_cats if r[2] == group_type]
                result.extend(
                    (cat, round(cat_m.get(cat, 0), 2), ctype, cat_det.get(cat, []))
                    for cat, ctype in group
                )
            return result

        # Mensile
        bil_spe_rows = q(conn, """SELECT e.category, e.euro, e.description, e.date
            FROM expenses e JOIN category c ON e.category=c.category COLLATE NOCASE
            WHERE e.user_id=1 AND strftime('%Y',e.date)=? AND strftime('%m',e.date)=?
            ORDER BY e.date DESC""", (str(bil_anno), f"{bil_mese:02d}"))
        bil_tot_ent = q(conn,
            "SELECT COALESCE(SUM(euro),0) FROM incomes WHERE user_id=1 AND strftime('%Y',date)=? AND strftime('%m',date)=?",
            (str(bil_anno), f"{bil_mese:02d}"))[0][0]
        bil_tot_spe = sum(r[1] for r in bil_spe_rows)
        bil_ess     = sum(r[1] for r in bil_spe_rows if type_map_bil.get(r[0]) == 'essential')
        bil_ext     = sum(r[1] for r in bil_spe_rows if type_map_bil.get(r[0]) == 'extra')
        bil_risp    = bil_tot_ent - bil_tot_spe
        chart_bar_bil = build_bar_chart(bil_spe_rows, ordered_cats, type_map_bil)
        bil_cats    = build_cat_list(bil_spe_rows, all_cats_ordered)
        bil_max     = max((r[1] for r in bil_cats), default=1) or 1

        # Annuale
        ann_spe_rows = q(conn, """SELECT e.category, e.euro, e.description, e.date
            FROM expenses e JOIN category c ON e.category=c.category COLLATE NOCASE
            WHERE e.user_id=1 AND strftime('%Y',e.date)=?
            ORDER BY e.date DESC""", (str(bil_anno),))
        ann_tot_ent = q(conn,
            "SELECT COALESCE(SUM(euro),0) FROM incomes WHERE user_id=1 AND strftime('%Y',date)=?",
            (str(bil_anno),))[0][0]
        ann_tot_spe = sum(r[1] for r in ann_spe_rows)
        ann_ess     = sum(r[1] for r in ann_spe_rows if type_map_bil.get(r[0]) == 'essential')
        ann_ext     = sum(r[1] for r in ann_spe_rows if type_map_bil.get(r[0]) == 'extra')
        ann_risp    = ann_tot_ent - ann_tot_spe
        chart_bar_ann_bil = build_bar_chart(ann_spe_rows, ordered_cats, type_map_bil)
        ann_cats    = build_cat_list(ann_spe_rows, all_cats_ordered)
        ann_max     = max((r[1] for r in ann_cats), default=1) or 1

        # Storico
        stor_period = request.args.get('period', '12m')
        stor_start, stor_end = parse_period(stor_period, today)
        if stor_start is None:  # 'all'
            row    = q(conn, "SELECT MIN(date) FROM (SELECT date FROM incomes WHERE user_id=1 UNION SELECT date FROM expenses WHERE user_id=1)")
            min_d  = row[0][0]
            stor_start = datetime.strptime(min_d, '%Y-%m-%d') if min_d else today

        stor_months = build_month_range(stor_start, stor_end)
        ss, se      = stor_start.strftime('%Y-%m-%d'), stor_end.strftime('%Y-%m-%d')

        stor_inc_rows = q(conn,
            "SELECT strftime('%Y',date) y, strftime('%m',date) m, SUM(euro) "
            "FROM incomes WHERE user_id=1 AND date BETWEEN ? AND ? GROUP BY y,m ORDER BY y,m", (ss, se))
        stor_exp_rows = q(conn, """SELECT strftime('%Y',e.date) y, strftime('%m',e.date) m, c.type, SUM(e.euro)
            FROM expenses e JOIN category c ON e.category=c.category COLLATE NOCASE
            WHERE e.user_id=1 AND e.date BETWEEN ? AND ? GROUP BY y,m,c.type ORDER BY y,m""", (ss, se))

        inc_map_s = {f"{r[0]}-{r[1]}": r[2] for r in stor_inc_rows}
        ess_map_s = {}
        ext_map_s = {}
        for r in stor_exp_rows:
            k = f"{r[0]}-{r[1]}"
            if r[2] == 'essential':
                ess_map_s[k] = ess_map_s.get(k, 0) + r[3]
            else:
                ext_map_s[k] = ext_map_s.get(k, 0) + r[3]

        h_inc = [inc_map_s.get(m, 0) for m in stor_months]
        h_ess = [ess_map_s.get(m, 0) for m in stor_months]
        h_ext = [ext_map_s.get(m, 0) for m in stor_months]

        hist_rows_bil, h_sav, stor_totals = build_hist_rows(stor_months, h_inc, h_ess, h_ext)
        hist_rows_bil = list(reversed(hist_rows_bil[:-1])) + [hist_rows_bil[-1]]
        chart_hist_bil = json.dumps({'labels': stor_months, 'essential': h_ess,
                                     'extra': h_ext, 'savings': h_sav, 'income': h_inc})

        bd = compute_budget(conn)
        cat_order = {cat: i for i, cat in enumerate(reversed(ordered_cats))}
        bd['budget_cats'].sort(key=lambda r: cat_order.get(r['category'], 999))

    return render_template('statistiche.html', empty=False,
        tab=tab, all_years=all_years, sel_year=sel_year,
        # tab 1
        cat_options=cat_options, cat_sel=cat_sel,
        years_av=years_av, anni_sel=anni_sel, stats=stats,
        cum_series=json.dumps(cum_series), monthly_series=json.dumps(monthly_series),
        # tab 2
        saving_rate_data=saving_rate_data, avg_sr=avg_sr, sr_year=sr_year,
        # tab 3
        proj_year=proj_year, proj_months_remaining=proj_months_remaining,
        proj_inc=proj_inc, proj_spe=proj_spe, proj_sav=proj_sav,
        ytd_inc=ytd_inc, ytd_spe=ytd_spe, ytd_sav=ytd_sav,
        avg_inc_proj=avg_inc_proj, avg_spe_proj=avg_spe_proj,
        # tab 4
        nec_ext_data=nec_ext_data, ne_year=ne_year,
        # tab 5
        anomalies=anomalies, anomaly_threshold=anomaly_threshold, anom_year=anom_year,
        # tab 6
        freq_data=freq_data, freq_year=freq_year,
        # tab 7
        sankey_data=sankey_data, sank_year=sank_year,
        mesi_it=MESI_IT,
        # tab bilancio
        bil_anno=bil_anno, bil_mese=bil_mese, bil_anni_range=bil_anni_range,
        mesi_it_full=mesi_it_full,
        bil_tot_ent=bil_tot_ent, bil_tot_spe=bil_tot_spe, bil_ess=bil_ess, bil_ext=bil_ext, bil_risp=bil_risp,
        chart_bar_bil=chart_bar_bil, bil_cats=bil_cats, bil_max=bil_max,
        ann_tot_ent=ann_tot_ent, ann_tot_spe=ann_tot_spe, ann_ess=ann_ess, ann_ext=ann_ext, ann_risp=ann_risp,
        chart_bar_ann_bil=chart_bar_ann_bil, ann_cats=ann_cats, ann_max=ann_max,
        # tab storico
        stor_period=stor_period, stor_nm=stor_totals['nm'],
        stor_tot_inc=stor_totals['tot_inc'], stor_tot_exp=stor_totals['tot_exp'], stor_tot_sav=stor_totals['tot_sav'],
        stor_avg_inc=stor_totals['avg_inc'], stor_avg_exp=stor_totals['avg_exp'], stor_avg_sav=stor_totals['avg_sav'],
        stor_tot_ess=stor_totals['tot_ess'], stor_tot_ext=stor_totals['tot_ext'],
        chart_hist_bil=chart_hist_bil, hist_rows_bil=hist_rows_bil,
        # budget stimato
        bd=bd,
    )
