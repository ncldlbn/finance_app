"""Dashboard: pagina di atterraggio dell'app (route '/'), sei pannelli in
griglia 3+3. Ogni pannello ha una query mirata e semplice — a differenza
delle tab di Statistiche non ha filtri, mostra sempre "adesso"."""
from flask import Blueprint, render_template, request
import sys, os, json, calendar
from datetime import datetime
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from db import finance_db
from helpers import (q, build_month_range, parse_period,
                     get_setting, get_setting_str, MESI_IT, MESI_IT_FULL)
from palette import YEAR_PALETTE, ESSENTIAL, EXTRA, SANKEY
from blueprints.extra import _ritmo_data
from blueprints.statistiche import _months_elapsed

dashboard_bp = Blueprint('dashboard', __name__)

SAVINGS_GOAL_VALUE_KEY  = 'savings_goal_value'
SAVINGS_GOAL_PERIOD_KEY = 'savings_goal_period'  # 'mensile' | 'annuale'


# ── Pannello 1: Sunburst (solo spese) + entrate/uscite/risparmio ────────────

def _panel_sunburst(conn, today, scope):
    if scope == 'anno':
        e_where, e_params = "strftime('%Y',e.date)=?", (str(today.year),)
        i_where, i_params = "strftime('%Y',date)=?", (str(today.year),)
        label = f"Anno {today.year}"
    else:
        e_where = "strftime('%Y',e.date)=? AND strftime('%m',e.date)=?"
        e_params = (str(today.year), f"{today.month:02d}")
        i_where = "strftime('%Y',date)=? AND strftime('%m',date)=?"
        i_params = e_params
        label = f"{MESI_IT_FULL[today.month]} {today.year}"

    income = q(conn, f"SELECT COALESCE(SUM(euro),0) FROM incomes WHERE user_id=1 AND {i_where}",
              i_params)[0][0]
    cat_rows = q(conn, f"""
        SELECT e.category, c.type, SUM(e.euro) FROM expenses e
        JOIN category c ON e.category=c.category COLLATE NOCASE
        WHERE e.user_id=1 AND {e_where}
        GROUP BY e.category, c.type ORDER BY 3 DESC""", e_params)

    total_spe = sum(r[2] for r in cat_rows)
    nec = sum(r[2] for r in cat_rows if r[1] == 'essential')
    ext = sum(r[2] for r in cat_rows if r[1] == 'extra')

    # Radicato su "Spese totali", non su "Entrate": le spese non possono mai
    # essere negative, quindi qui non esiste il vincolo di contenimento che
    # limita il Sunburst di Statistiche (spese > entrate rompe un anello
    # radicato sulle entrate, non uno radicato sulle spese stesse).
    ids, labels, parents, values, colors = (
        ['spese'], ['Spese totali'], [''], [round(total_spe, 2)], [SANKEY['node_neutral']])
    if nec > 0:
        ids.append('necessita'); labels.append('Necessità'); parents.append('spese')
        values.append(round(nec, 2)); colors.append(ESSENTIAL)
    if ext > 0:
        ids.append('extra'); labels.append('Extra'); parents.append('spese')
        values.append(round(ext, 2)); colors.append(EXTRA)
    for cat, ctype, tot in cat_rows:
        if tot < 1:
            continue
        ids.append(f'cat-{ctype}-{cat}'); labels.append(cat)
        parents.append('necessita' if ctype == 'essential' else 'extra')
        values.append(round(tot, 2)); colors.append(SANKEY['node_cat'])

    return {
        'label': label, 'has_data': total_spe > 0,
        'income': round(income, 2), 'expense': round(total_spe, 2),
        'risparmio': round(income - total_spe, 2),
        'sunburst_data': json.dumps({'ids': ids, 'labels': labels, 'parents': parents,
                                     'values': values, 'colors': colors}),
    }


# ── Pannello 2 (vista "Categorie"): spesa extra annuale per categoria ────────

def _extra_by_category(conn, today):
    rows = q(conn, """
        SELECT e.category, SUM(e.euro) FROM expenses e
        JOIN category c ON e.category=c.category COLLATE NOCASE
        WHERE e.user_id=1 AND strftime('%Y',e.date)=? AND c.type='extra'
        GROUP BY e.category HAVING SUM(e.euro) > 0 ORDER BY 2 DESC""", (str(today.year),))
    return json.dumps({'labels': [r[0] for r in rows], 'values': [round(r[1], 2) for r in rows]})


# ── Pannello 3: obiettivo di risparmio ───────────────────────────────────────

def _panel_savings_goal(conn, today):
    """Stessa logica del Ritmo extra (anello + barretta di oggi), ma qui
    l'anello si riempie mano a mano che si risparmia verso un obiettivo,
    invece che svuotarsi consumando un budget. Obiettivo impostato in
    Impostazioni: un valore + uno switch mensile/annuale (il valore è
    sempre quello del periodo scelto, l'altro si ricava moltiplicando o
    dividendo per 12)."""
    period = get_setting_str(conn, SAVINGS_GOAL_PERIOD_KEY, 'annuale')
    value = get_setting(conn, SAVINGS_GOAL_VALUE_KEY, 0.0)
    goal_annual = value * 12 if period == 'mensile' else value

    result = {'available': value > 0, 'period': period, 'value': round(value, 2),
              'goal_annual': 0, 'saved_ytd': 0, 'pct': 0, 'avg_monthly': 0, 'residuo': 0, 'residuo_mensile': 0, 'today_angle': 0, 'today_label': ''}
    if not result['available']:
        return result

    inc = q(conn, "SELECT COALESCE(SUM(euro),0) FROM incomes WHERE user_id=1 "
                 "AND strftime('%Y',date)=?", (str(today.year),))[0][0]
    exp = q(conn, "SELECT COALESCE(SUM(euro),0) FROM expenses WHERE user_id=1 "
                 "AND strftime('%Y',date)=?", (str(today.year),))[0][0]
    saved_ytd = round(inc - exp, 2)

    yr_len = 366 if calendar.isleap(today.year) else 365
    today_doy = today.timetuple().tm_yday
    result.update(
        goal_annual=round(goal_annual, 2), saved_ytd=saved_ytd,
        pct=round(saved_ytd / goal_annual * 100, 1) if goal_annual else 0,
        today_angle=round(today_doy / yr_len * 360, 2),
        today_label=f"{today.day} {MESI_IT[today.month - 1].lower()}",
        avg_monthly=round(saved_ytd / max(_months_elapsed(today), 1), 2),
    )
    # Residuo e residuo mensile calcolati come per l'extra: quanto manca,
    # spalmato sui giorni rimasti dell'anno (x30).
    residuo = round(goal_annual - saved_ytd, 2)
    result.update(residuo=residuo,
                  residuo_mensile=round(residuo / max(yr_len - today_doy, 1) * 30, 2))
    return result


# ── Pannello 4: andamento YTD (anno corrente) ────────────────────────────────

def _panel_andamento_ytd(conn, today):
    start, end = parse_period('ytd', today)
    months = build_month_range(start, end)
    ss, se = start.strftime('%Y-%m-%d'), end.strftime('%Y-%m-%d')

    inc_rows = q(conn, "SELECT strftime('%Y-%m',date), SUM(euro) FROM incomes "
                       "WHERE user_id=1 AND date BETWEEN ? AND ? GROUP BY 1", (ss, se))
    # Spese TOTALI per mese (tutte le spese, categorizzate o no): il risparmio
    # è entrate - spese totali e non deve dipendere dal fatto che ogni spesa
    # abbia una categoria con tipo. La ripartizione necessità/extra qui sotto
    # serve solo alla vista "spese" impilata.
    tot_rows = q(conn, "SELECT strftime('%Y-%m',date), SUM(euro) FROM expenses "
                       "WHERE user_id=1 AND date BETWEEN ? AND ? GROUP BY 1", (ss, se))
    split_rows = q(conn, """
        SELECT strftime('%Y-%m',e.date), c.type, SUM(e.euro)
        FROM expenses e JOIN category c ON e.category=c.category COLLATE NOCASE
        WHERE e.user_id=1 AND e.date BETWEEN ? AND ? GROUP BY 1,2""", (ss, se))

    inc_map = {r[0]: r[1] for r in inc_rows}
    tot_map = {r[0]: r[1] for r in tot_rows}
    ess_map, ext_map = defaultdict(float), defaultdict(float)
    for ym, ctype, tot in split_rows:
        (ess_map if ctype == 'essential' else ext_map)[ym] += tot

    h_inc = [round(inc_map.get(m, 0), 2) for m in months]
    h_ess = [round(ess_map.get(m, 0), 2) for m in months]
    h_ext = [round(ext_map.get(m, 0), 2) for m in months]
    h_sav = [round(h_inc[i] - tot_map.get(months[i], 0), 2) for i in range(len(months))]

    return json.dumps({'labels': months, 'income': h_inc, 'essential': h_ess,
                       'extra': h_ext, 'savings': h_sav})


# ── Pannello 5: cumulata spese ───────────────────────────────────────────────

def _slope(doy_map, n_days):
    """Pendenza (€/giorno) della retta ai minimi quadrati sulla cumulata
    giornaliera dal giorno 1 al giorno n_days (la cumulata vale anche nei
    giorni senza spese, così la stima non dipende da quando cadono)."""
    cumul, ys = 0.0, []
    for d in range(1, n_days + 1):
        cumul += doy_map.get(d, 0.0)
        ys.append(cumul)
    n = len(ys)
    if n < 2:
        return None
    mx, my = (n + 1) / 2, sum(ys) / n
    den = sum((x - mx) ** 2 for x in range(1, n + 1))
    return sum((x - mx) * (y - my) for x, y in zip(range(1, n + 1), ys)) / den


def _panel_cumulata(conn, today):
    """Cumulata delle spese dell'anno corrente, con l'anno precedente come
    riferimento (stessa costruzione della cumulata di Statistiche/Categorie,
    ristretta a 'Totale'). In più, il delta di pendenza: due rette ai minimi
    quadrati sulla stessa finestra (1 gennaio → oggi) nei due anni; il
    rapporto delle pendenze è la variazione % annuale dei costi."""
    years = sorted({today.year - 1, today.year})
    ph = ','.join('?' * len(years))
    rows = q(conn, f"SELECT date, euro FROM expenses WHERE user_id=1 "
                   f"AND strftime('%Y',date) IN ({ph})", tuple(str(y) for y in years))

    cum_series, doy_maps = [], {}
    for yr in years:
        doy_map = defaultdict(float)
        for d, e in rows:
            if d.startswith(str(yr)):
                doy_map[datetime.strptime(d, '%Y-%m-%d').timetuple().tm_yday] += e
        doy_maps[yr] = doy_map
        cumul, xs, ys = 0, [], []
        for day in sorted(doy_map):
            cumul += doy_map[day]
            xs.append(day); ys.append(round(cumul, 2))
        # Anno corrente in bianco, anno precedente in grigio.
        color = '#ffffff' if yr == today.year else '#8a8f99'
        cum_series.append({'year': str(yr), 'x': xs, 'y': ys, 'color': color})

    delta = None
    n_days = today.timetuple().tm_yday
    prev = doy_maps.get(today.year - 1)
    if prev:
        s_cur = _slope(doy_maps[today.year], n_days)
        s_prev = _slope(prev, n_days)
        if s_cur is not None and s_prev and s_prev > 0:
            delta = {'pct': round((s_cur / s_prev - 1) * 100, 1),
                     'cur': round(s_cur * 30, 2), 'prev': round(s_prev * 30, 2),
                     'prev_year': today.year - 1}

    return {'series': json.dumps(cum_series), 'delta': delta}


# ── Pannello 6: bilancio attuale (mese/anno, toggle proprio) ────────────────

def _panel_bilancio(conn, today, scope_bil):
    if scope_bil == 'anno':
        e_where, e_params = "strftime('%Y',e.date)=?", (str(today.year),)
        i_where, i_params = "strftime('%Y',date)=?", (str(today.year),)
        label = f"Anno {today.year}"
    else:
        e_where = "strftime('%Y',e.date)=? AND strftime('%m',e.date)=?"
        e_params = (str(today.year), f"{today.month:02d}")
        i_where = "strftime('%Y',date)=? AND strftime('%m',date)=?"
        i_params = e_params
        label = f"{MESI_IT_FULL[today.month]} {today.year}"

    income = q(conn, f"SELECT COALESCE(SUM(euro),0) FROM incomes WHERE user_id=1 AND {i_where}",
              i_params)[0][0]
    cat_rows = q(conn, f"""
        SELECT c.type, SUM(e.euro) FROM expenses e
        JOIN category c ON e.category=c.category COLLATE NOCASE
        WHERE e.user_id=1 AND {e_where} GROUP BY c.type""", e_params)
    type_map = dict(cat_rows)
    nec, ext = type_map.get('essential', 0), type_map.get('extra', 0)
    expense = nec + ext
    risparmio = income - expense
    pct = lambda v: round(v / income * 100, 1) if income else 0

    return {'label': label, 'income': round(income, 2), 'expense': round(expense, 2),
           'essential': round(nec, 2), 'extra': round(ext, 2), 'risparmio': round(risparmio, 2),
           'pct_expense': pct(expense), 'pct_essential': pct(nec), 'pct_extra': pct(ext),
           'pct_risparmio': pct(risparmio)}


@dashboard_bp.route('/')
def index():
    today = datetime.today()
    scope = request.args.get('scope', 'mese')
    if scope not in ('mese', 'anno'):
        scope = 'mese'
    scope_bil = request.args.get('scope_bil', 'mese')
    if scope_bil not in ('mese', 'anno'):
        scope_bil = 'mese'

    with finance_db() as conn:
        sunburst = _panel_sunburst(conn, today, scope)
        ritmo_extra = _ritmo_data(conn, today)
        extra_cats = _extra_by_category(conn, today)
        savings_goal = _panel_savings_goal(conn, today)
        andamento_ytd = _panel_andamento_ytd(conn, today)
        cumulata = _panel_cumulata(conn, today)
        bilancio = _panel_bilancio(conn, today, scope_bil)

    return render_template('dashboard.html',
        scope=scope, scope_bil=scope_bil, sunburst=sunburst, ritmo_extra=ritmo_extra, extra_cats=extra_cats,
        savings_goal=savings_goal, andamento_ytd=andamento_ytd,
        cum_series=cumulata['series'], cum_delta=cumulata['delta'], year=today.year,
        bilancio=bilancio)
