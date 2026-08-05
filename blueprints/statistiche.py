"""Pagina Statistiche.

Quattro tab, ognuna calcolata solo quando è quella attiva (lo switch è
server-side, come già avviene per i filtri):

  bilancio   — mese / anno / budget stimato: stessa struttura, periodo diverso
  andamento  — storico, saving rate, proiezione, anomalie: l'asse temporale
  categorie  — spese per anno, necessità vs extra, frequenza: l'asse categorie
  flusso     — Sankey entrate → risparmio/spese → categorie
"""
from flask import Blueprint, render_template, request
import json, statistics, calendar, sys, os
from datetime import datetime, timedelta
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from db import finance_db
from helpers import (q, build_month_range, build_monthly_maps, build_hist_rows,
                     parse_period, compute_budget, MESI_IT, MESI_IT_FULL)
from palette import YEAR_PALETTE, ESSENTIAL, EXTRA, SANKEY

statistiche_bp = Blueprint('statistiche', __name__)

TABS = ('bilancio', 'andamento', 'categorie', 'flusso')


# ── Utility condivise ────────────────────────────────────────────────────────

def _months_elapsed(today):
    """Mesi trascorsi nell'anno, contando quello corrente pro-quota.

    Serve per le medie mensili dell'anno in corso: il 5 agosto sono trascorsi
    7.16 mesi, non 8, e dividere per 8 sottostima sistematicamente la media."""
    dim = calendar.monthrange(today.year, today.month)[1]
    return today.month - 1 + today.day / dim


def _all_years(conn):
    return sorted(r[0] for r in q(conn, """
        SELECT DISTINCT strftime('%Y', date) FROM (
            SELECT date FROM incomes  WHERE user_id=1
            UNION
            SELECT date FROM expenses WHERE user_id=1)"""))


def _categories(conn):
    """[(categoria, tipo)] in ordine di id."""
    return [(r[0], r[1]) for r in q(conn, "SELECT category, type FROM category ORDER BY id")]


def _pick_year(args, all_years, today, param='anno'):
    y = args.get(param, str(today.year))
    return int(y) if y in all_years else int(all_years[-1])


# ── Tab: BILANCIO ────────────────────────────────────────────────────────────

def _tab_bilancio(conn, args, today, all_years):
    """Mese, anno e budget stimato condividono la stessa struttura visiva:
    cinque metriche di sintesi + la lista categorie a barre. Cambia solo il
    periodo di riferimento, quindi normalizziamo i tre casi sullo stesso dict."""
    mode = args.get('mode', 'mese')
    if mode not in ('mese', 'anno', 'budget'):
        mode = 'mese'

    cats_master = _categories(conn)
    anno = _pick_year(args, all_years, today)
    mese = int(args.get('mese', today.month))
    if not 1 <= mese <= 12:
        mese = today.month

    ctx = {'mode': mode, 'bil_anno': anno, 'bil_mese': mese,
           'anni_range': [int(y) for y in all_years], 'mesi_it_full': MESI_IT_FULL}

    if mode == 'budget':
        bd = compute_budget(conn)
        order = {c: i for i, (c, _) in enumerate(cats_master)}
        cats = [{'name': r['category'], 'amount': r['estimate'], 'type': r['type'],
                 'details': None, 'meta': r}
                for r in sorted(bd['budget_cats'],
                                key=lambda r: (0 if r['type'] == 'essential' else 1,
                                               order.get(r['category'], 999)))]
        ctx.update(label='Mese tipico',
                   sublabel=f"stima su {bd['budget_window']} mesi ({bd['budget_period']})",
                   estimated=True,
                   income=bd['est_income'], expense=bd['est_expense'],
                   essential=bd['est_essential'], extra=bd['est_extra'],
                   savings=bd['est_savings'],
                   cats=cats, cat_max=bd['budget_max'],
                   cats_json=_cats_for_treemap(cats))
        return ctx

    if mode == 'anno':
        e_where, e_params = "strftime('%Y',e.date)=?", (str(anno),)
        i_where, i_params = "strftime('%Y',date)=?",  (str(anno),)
        label = f"Anno {anno}"
    else:
        e_where = "strftime('%Y',e.date)=? AND strftime('%m',e.date)=?"
        e_params = (str(anno), f"{mese:02d}")
        i_where = "strftime('%Y',date)=? AND strftime('%m',date)=?"
        i_params = e_params
        label = f"{MESI_IT_FULL[mese]} {anno}"

    spe_rows = q(conn, f"""
        SELECT e.category, e.euro, e.description, e.date, c.type
        FROM expenses e JOIN category c ON e.category=c.category COLLATE NOCASE
        WHERE e.user_id=1 AND {e_where}
        ORDER BY e.date DESC""", e_params)
    income = q(conn, f"SELECT COALESCE(SUM(euro),0) FROM incomes "
                     f"WHERE user_id=1 AND {i_where}", i_params)[0][0]

    agg, det = defaultdict(float), defaultdict(list)
    ess = ext = 0.0
    for cat, euro, desc, date, ctype in spe_rows:
        agg[cat] += euro
        det[cat].append((date, desc, euro))
        if ctype == 'essential':
            ess += euro
        else:
            ext += euro

    # Tutte le categorie, anche a zero: l'assenza di spesa è un'informazione.
    cats = [{'name': cat, 'amount': round(agg.get(cat, 0), 2), 'type': ctype,
             'details': det.get(cat, []), 'meta': None}
            for group in ('essential', 'extra')
            for cat, ctype in cats_master if ctype == group]

    ctx.update(label=label, sublabel=None, estimated=False,
               income=income, expense=ess + ext, essential=ess, extra=ext,
               savings=income - (ess + ext),
               cats=cats, cat_max=max((c['amount'] for c in cats), default=1) or 1,
               cats_json=_cats_for_treemap(cats))
    return ctx


def _cats_for_treemap(cats):
    """Treemap piatta, colorata solo per necessità/extra (mai una tinta per
    categoria: sono fino a 21, ben oltre il tetto di 8 tinte distinguibili).
    Le categorie a zero non hanno un riquadro possibile, quindi qui — a
    differenza della lista, dove l'assenza di spesa è un'informazione — si
    escludono."""
    return json.dumps([{'name': c['name'], 'amount': c['amount'], 'type': c['type']}
                       for c in cats if c['amount'] > 0])


# ── Tab: ANDAMENTO ───────────────────────────────────────────────────────────

def _tab_andamento(conn, args, today, all_years):
    """Storico, saving rate e anomalie derivano tutti dalle stesse serie
    mensili: una sola lettura, tre letture diverse degli stessi numeri."""
    period = args.get('period', '12m')
    start, end = parse_period(period, today)
    if start is None:  # 'all'
        row = q(conn, """SELECT MIN(date) FROM (
                             SELECT date FROM incomes  WHERE user_id=1
                             UNION
                             SELECT date FROM expenses WHERE user_id=1)""")
        start = datetime.strptime(row[0][0], '%Y-%m-%d') if row[0][0] else today

    months = build_month_range(start, end)
    ss, se = start.strftime('%Y-%m-%d'), end.strftime('%Y-%m-%d')

    inc_rows = q(conn, "SELECT strftime('%Y-%m',date), SUM(euro) FROM incomes "
                       "WHERE user_id=1 AND date BETWEEN ? AND ? GROUP BY 1", (ss, se))
    exp_rows = q(conn, """
        SELECT strftime('%Y-%m',e.date), c.type, SUM(e.euro)
        FROM expenses e JOIN category c ON e.category=c.category COLLATE NOCASE
        WHERE e.user_id=1 AND e.date BETWEEN ? AND ? GROUP BY 1,2""", (ss, se))

    inc_map = {r[0]: r[1] for r in inc_rows}
    ess_map, ext_map = defaultdict(float), defaultdict(float)
    for ym, ctype, tot in exp_rows:
        (ess_map if ctype == 'essential' else ext_map)[ym] += tot

    h_inc = [inc_map.get(m, 0) for m in months]
    h_ess = [ess_map.get(m, 0) for m in months]
    h_ext = [ext_map.get(m, 0) for m in months]

    hist_rows, h_sav, totals = build_hist_rows(months, h_inc, h_ess, h_ext)
    hist_rows = list(reversed(hist_rows[:-1])) + [hist_rows[-1]]  # recenti in cima, totale in fondo

    # ── Saving rate: None sui mesi senza entrate, così il grafico interrompe
    # la linea invece di disegnare uno 0% che non significa nulla.
    sr_rates = [round(h_sav[i] / h_inc[i] * 100, 1) if h_inc[i] > 0 else None
                for i in range(len(months))]
    sr_valid = [r for r in sr_rates if r is not None][-12:]
    avg_sr = round(sum(sr_valid) / len(sr_valid), 1) if sr_valid else 0

    # ── Proiezione: sempre sull'anno in corso (proiettare un anno chiuso non
    # ha senso). Come finestra di riferimento prendiamo gli ultimi 3 mesi
    # completi *con entrate registrate*: sono i mesi davvero consuntivati, e
    # usare la stessa finestra per entrate e spese mantiene coerente il
    # risparmio implicito. Con la sola regola "ultimi 3 mesi completi" bastano
    # un paio di mesi non ancora compilati per azzerare la stima.
    inc_y, spe_y = build_monthly_maps(conn, str(today.year))
    ytd_inc = sum(inc_y.values())
    ytd_spe = sum(spe_y.values())
    done = [f"{today.year}-{m:02d}" for m in range(1, today.month)]
    ref = [m for m in done if inc_y.get(m, 0) > 0][-3:] or done[-3:]
    avg_inc = sum(inc_y.get(m, 0) for m in ref) / len(ref) if ref else 0
    avg_spe = sum(spe_y.get(m, 0) for m in ref) / len(ref) if ref else 0
    remaining = 12 - _months_elapsed(today)  # quota d'anno ancora da coprire
    proj = {
        'year': today.year, 'remaining': round(remaining, 1),
        'ref_labels': [MESI_IT[int(m[5:]) - 1] for m in ref],
        'ytd_inc': ytd_inc, 'ytd_spe': ytd_spe, 'ytd_sav': ytd_inc - ytd_spe,
        'avg_inc': avg_inc, 'avg_spe': avg_spe,
        'inc': ytd_inc + avg_inc * remaining,
        'spe': ytd_spe + avg_spe * remaining,
    }
    proj['sav'] = proj['inc'] - proj['spe']

    return {
        'period': period,
        'stor_nm': totals['nm'], 'hist_rows': hist_rows, 'totals': totals,
        'chart_hist': json.dumps({'labels': months, 'essential': h_ess,
                                  'extra': h_ext, 'savings': h_sav, 'income': h_inc}),
        'saving_rate_data': json.dumps({'labels': months, 'rates': sr_rates,
                                        'avg': avg_sr}),
        'avg_sr': avg_sr,
        'proj': proj,
    }


def _cumulative_projection(frows, anni_sel, year_doy_cum, today, cur_year_color, inc_months):
    """Proiezione a ventaglio per l'anno in corso: dove finisce la cumulata di
    oggi entro fine anno.

    Centrale (sempre presente se l'anno in corso è tra quelli selezionati):
    ritmo medio degli ultimi 3 mesi completi con dati reali, esteso in linea
    retta — stessa logica già usata in Andamento, qui ricalcolata sul filtro
    categoria/anni attivo in questa tab.

    Banda (solo se c'è almeno un altro anno selezionato con cui confrontarsi):
    per ciascun anno di confronto, si riscala la sua curva cumulata in modo
    che coincida con lo speso reale di oggi, e se ne segue la forma fino a
    fine anno — cioè "se il resto dell'anno andasse come è andato quell'anno
    lì". La banda è l'inviluppo min/max fra questi anni riscalati, allargata
    se necessario a contenere sempre la centrale (una stima fuori dal proprio
    intervallo storico sarebbe una lettura confusa). Senza anni di confronto
    resta solo la centrale tratteggiata, dichiarato in caption — niente banda
    finta.

    Semplificazione nota: l'allineamento fra anni è per numero di giorno
    dell'anno grezzo, non per frazione dell'anno — stessa approssimazione già
    accettata altrove nel grafico per gli anni bisestili (± 1 giorno vicino a
    fine anno in un anno bisestile, cosmetico)."""
    if today.year not in year_doy_cum or today.year not in anni_sel:
        return None

    yr_len = 366 if calendar.isleap(today.year) else 365
    doy_today = min(today.timetuple().tm_yday, yr_len)

    def step_value(pairs, day):
        val = 0.0
        for d, v in pairs:
            if d > day:
                break
            val = v
        return val

    cur_pairs = year_doy_cum[today.year]
    actual_ytd = step_value(cur_pairs, doy_today)

    cur_year_rows = [r for r in frows if r[0] == today.year]
    m_tot = defaultdict(float)
    for r in cur_year_rows:
        m_tot[r[1]] += r[3]
    done_months = list(range(1, today.month))
    # "Mese con spesa" non basta: una singola ricorrente automatica di pochi
    # euro rende non-zero anche un mese in cui la categoria filtrata non è
    # stata davvero usata (visto succedere: giu/lug con soli 7€ di
    # abbonamento). Le entrate sono inserite a mano una tantum, quindi la
    # loro presenza è un segnale più affidabile di "mese vissuto" — stessa
    # regola già usata per la Proiezione in Andamento.
    ref_months = [m for m in done_months
                  if inc_months.get(f"{today.year}-{m:02d}", 0) > 0][-3:] or done_months[-3:]
    avg_daily = (sum(m_tot.get(m, 0) for m in ref_months) / len(ref_months) / (365.25 / 12)
                if ref_months else 0)

    remaining = list(range(doy_today + 1, yr_len + 1))
    fan_x = [doy_today] + remaining
    central = [round(actual_ytd, 2)] + [round(actual_ytd + avg_daily * (d - doy_today), 2)
                                        for d in remaining]

    compare_years = [y for y in anni_sel if y != today.year and y in year_doy_cum]
    band_lo, band_hi, used_years = [], [], []
    trajectories = []
    for y in compare_years:
        pairs = year_doy_cum[y]
        y_today = step_value(pairs, doy_today)
        if y_today <= 0:
            continue
        trajectories.append([actual_ytd * step_value(pairs, d) / y_today for d in remaining])
        used_years.append(y)
    if trajectories:
        band_lo = [min(t[i] for t in trajectories) for i in range(len(remaining))]
        band_hi = [max(t[i] for t in trajectories) for i in range(len(remaining))]
        for i in range(len(remaining)):
            band_lo[i] = round(min(band_lo[i], central[i + 1]), 2)
            band_hi[i] = round(max(band_hi[i], central[i + 1]), 2)
        band_lo = [round(actual_ytd, 2)] + band_lo
        band_hi = [round(actual_ytd, 2)] + band_hi

    return {
        'year': today.year, 'color': cur_year_color,
        'x': fan_x, 'central': central, 'band_lo': band_lo, 'band_hi': band_hi,
        'ref_months': [MESI_IT[m - 1] for m in ref_months],
        'compare_years': used_years,
    }


# ── Tab: CATEGORIE ───────────────────────────────────────────────────────────

def _tab_categorie(conn, args, today, all_years):
    """Un solo filtro anni per tutta la tab; il filtro categoria agisce solo
    sulla prima sezione. Tutte e tre le sezioni derivano da un'unica query."""
    years_av = [int(y) for y in all_years]
    chosen   = [int(a) for a in args.getlist('anni') if a.isdigit()]
    anni_sel = sorted(y for y in chosen if y in years_av) or years_av[-3:]

    cats_master = _categories(conn)
    cat_sel = args.get('categoria', 'Totale')
    cat_options = (['Totale', 'Totale necessità', 'Totale extra']
                   + [c for c, _ in cats_master])
    if cat_sel not in cat_options:
        cat_sel = 'Totale'

    ph = ','.join('?' * len(anni_sel))
    rows = q(conn, f"""
        SELECT e.date, e.euro, e.category, c.type
        FROM expenses e JOIN category c ON e.category=c.category COLLATE NOCASE
        WHERE e.user_id=1 AND strftime('%Y',e.date) IN ({ph})""",
        tuple(str(y) for y in anni_sel))

    # (anno, mese, giorno-dell'anno, euro, categoria, tipo)
    parsed = []
    for date, euro, cat, ctype in rows:
        d = datetime.strptime(date, '%Y-%m-%d')
        parsed.append((d.year, d.month, d.timetuple().tm_yday, euro, cat, ctype))

    if cat_sel == 'Totale':
        frows = parsed
    elif cat_sel == 'Totale necessità':
        frows = [r for r in parsed if r[5] == 'essential']
    elif cat_sel == 'Totale extra':
        frows = [r for r in parsed if r[5] == 'extra']
    else:
        frows = [r for r in parsed if r[4] == cat_sel]

    # ── Sezione 1: riepilogo per anno + cumulata + confronto mensile
    stats, cum_series, monthly_series = [], [], []
    year_doy_cum = {}  # yr -> [(giorno, cumulata)]: riusato dalla proiezione più sotto
    for i, yr in enumerate(anni_sel):
        yr_rows = [r for r in frows if r[0] == yr]
        total   = sum(r[3] for r in yr_rows)
        mesi    = _months_elapsed(today) if yr == today.year else 12
        avg_m   = total / mesi if mesi > 0 else 0

        m_tot = defaultdict(float)
        for r in yr_rows:
            m_tot[r[1]] += r[3]
        active = {m: v for m, v in m_tot.items() if v > 0}
        if active:
            mx, mn = max(active, key=active.get), min(active, key=active.get)
            min_info = f"€{active[mn]:,.0f} ({MESI_IT[mn-1].lower()})"
            max_info = f"€{active[mx]:,.0f} ({MESI_IT[mx-1].lower()})"
            std_dev  = statistics.pstdev(list(active.values())) if len(active) > 1 else 0
        else:
            min_info = max_info = 'N/D'
            std_dev = 0

        # Il confronto è con l'anno precedente *fra quelli selezionati*: lo
        # esplicitiamo nella colonna, altrimenti con selezioni non contigue
        # (es. 2021 e 2024) l'etichetta "anno prec." sarebbe fuorviante.
        delta_str, prev_yr = '–', None
        if i > 0:
            prev_yr   = anni_sel[i - 1]
            prev_tot  = sum(r[3] for r in frows if r[0] == prev_yr)
            prev_mesi = _months_elapsed(today) if prev_yr == today.year else 12
            prev_avg  = prev_tot / prev_mesi if prev_mesi > 0 else 0
            delta_str = f"{((avg_m - prev_avg) / prev_avg * 100):+.1f}%" if prev_avg else 'N/D'

        stats.append({'anno': yr, 'totale': total, 'media': avg_m, 'std': std_dev,
                      'min': min_info, 'max': max_info,
                      'delta': delta_str, 'prev': prev_yr})

        doy_map = defaultdict(float)
        for r in yr_rows:
            doy_map[r[2]] += r[3]
        cumul, xs, ys, labels = 0, [], [], []
        for d in sorted(doy_map):
            cumul += doy_map[d]
            xs.append(d)
            ys.append(round(cumul, 2))
            # asse x = giorno dell'anno (sovrapponibile fra anni), etichetta DD/MM
            labels.append((datetime(yr, 1, 1) + timedelta(days=d - 1)).strftime('%d/%m'))
        color = YEAR_PALETTE[i % len(YEAR_PALETTE)]
        cum_series.append({'year': str(yr), 'x': xs, 'y': ys, 'labels': labels, 'color': color})
        monthly_series.append({'year': str(yr),
                               'values': [round(m_tot.get(m, 0), 2) for m in range(1, 13)],
                               'color': color})
        year_doy_cum[yr] = list(zip(xs, ys))
        if yr == today.year:
            cur_year_color = color

    inc_months, _ = build_monthly_maps(conn, str(today.year))
    fan = _cumulative_projection(frows, anni_sel, year_doy_cum, today,
                                 cur_year_color if today.year in year_doy_cum else None,
                                 inc_months)

    return {
        'cat_options': cat_options, 'cat_sel': cat_sel,
        'years_av': years_av, 'anni_sel': anni_sel,
        'stats': stats,
        'cum_series': json.dumps(cum_series),
        'monthly_series': json.dumps(monthly_series),
        'fan': fan, 'fan_data': json.dumps(fan) if fan else 'null',
    }


# ── Tab: FLUSSO ──────────────────────────────────────────────────────────────

def _tab_flusso(conn, args, today, all_years):
    anno = _pick_year(args, all_years, today)

    total_inc = q(conn, "SELECT COALESCE(SUM(euro),0) FROM incomes "
                        "WHERE user_id=1 AND strftime('%Y',date)=?", (str(anno),))[0][0]
    cat_rows = q(conn, """
        SELECT e.category, c.type, SUM(e.euro)
        FROM expenses e JOIN category c ON e.category=c.category
        WHERE e.user_id=1 AND strftime('%Y',e.date)=?
        GROUP BY e.category, c.type ORDER BY 3 DESC""", (str(anno),))

    total_spe = sum(r[2] for r in cat_rows)
    risparmio = total_inc - total_spe
    nec = sum(r[2] for r in cat_rows if r[1] == 'essential')
    ext = sum(r[2] for r in cat_rows if r[1] == 'extra')

    # Solo tre classi cromatiche portano significato (risparmio, necessità,
    # extra): i nodi di passaggio restano neutri. Nel Sankey ogni nodo può
    # finire accanto a ogni altro, e più di tre tinte non si distinguono.
    nodes   = ['Entrate', 'Risparmio', 'Spese totali', 'Necessità', 'Extra']
    n_col   = [SANKEY['node_neutral'], SANKEY['node_savings'],
               SANKEY['node_neutral'], ESSENTIAL, EXTRA]
    src, tgt, val, l_col = [], [], [], []
    cat_link = {'essential': SANKEY['link_cat_ess'], 'extra': SANKEY['link_cat_ext']}

    def link(s, t, v, c):
        src.append(s); tgt.append(t); val.append(round(v, 2)); l_col.append(c)

    if risparmio > 0:
        link(0, 1, risparmio, SANKEY['link_savings'])
    link(0, 2, total_spe, SANKEY['link_expense'])
    if nec > 0:
        link(2, 3, nec, SANKEY['link_essential'])
    if ext > 0:
        link(2, 4, ext, SANKEY['link_extra'])
    for cat, ctype, tot in cat_rows:
        if tot < 1:
            continue
        nodes.append(cat)
        n_col.append(SANKEY['node_cat'])
        link(3 if ctype == 'essential' else 4, len(nodes) - 1, tot,
             cat_link.get(ctype, SANKEY['link_cat_ext']))

    # ── Sunburst: stessa gerarchia del Sankey (entrate → risparmio/spese →
    # necessità/extra → categorie), come anelli concentrici invece che come
    # flusso. A differenza del Sankey — dove un link è solo una freccia fra
    # due nodi — un anello è un CONTENITORE: la fetta "Spese totali" non può
    # essere più grande della fetta "Entrate" che la contiene. Con spese >
    # entrate (risparmio negativo, tutt'altro che raro) la gerarchia non sta
    # in piedi geometricamente, quindi in quel caso non la costruiamo: il
    # Flusso resta l'unica vista, perché lì il vincolo non esiste.
    sun_available = (total_inc > 0 or total_spe > 0) and risparmio >= 0
    sun_ids, sun_labels, sun_parents, sun_values, sun_colors = [], [], [], [], []
    if sun_available:
        def node(id_, label, parent, value, color):
            sun_ids.append(id_); sun_labels.append(label); sun_parents.append(parent)
            sun_values.append(round(value, 2)); sun_colors.append(color)

        node('entrate', 'Entrate', '', total_inc, SANKEY['node_neutral'])
        node('spese', 'Spese totali', 'entrate', total_spe, SANKEY['node_neutral'])
        if risparmio > 0:
            node('risparmio', 'Risparmio', 'entrate', risparmio, SANKEY['node_savings'])
        if nec > 0:
            node('necessita', 'Necessità', 'spese', nec, ESSENTIAL)
        if ext > 0:
            node('extra', 'Extra', 'spese', ext, EXTRA)
        for cat, ctype, tot in cat_rows:
            if tot < 1:
                continue
            node(f'cat-{ctype}-{cat}', cat, 'necessita' if ctype == 'essential' else 'extra',
                 tot, SANKEY['node_cat'])

    return {
        'sank_anno': anno,
        'sankey_data': json.dumps({'nodes': nodes, 'node_colors': n_col,
                                   'sources': src, 'targets': tgt,
                                   'values': val, 'link_colors': l_col}),
        'sunburst_available': sun_available,
        'sunburst_data': json.dumps({'ids': sun_ids, 'labels': sun_labels,
                                     'parents': sun_parents, 'values': sun_values,
                                     'colors': sun_colors}),
    }


# ── Routing ──────────────────────────────────────────────────────────────────

_BUILDERS = {'bilancio': _tab_bilancio, 'andamento': _tab_andamento,
             'categorie': _tab_categorie, 'flusso': _tab_flusso}


@statistiche_bp.route('/statistiche')
def index():
    today = datetime.today()
    tab = request.args.get('tab', 'bilancio')
    if tab not in TABS:
        tab = 'bilancio'

    with finance_db() as conn:
        all_years = _all_years(conn)
        if not all_years:
            return render_template('statistiche.html', empty=True, tab=tab)
        ctx = _BUILDERS[tab](conn, request.args, today, all_years)

    return render_template('statistiche.html', empty=False, tab=tab,
                           all_years=all_years, **ctx)
