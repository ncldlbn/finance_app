"""Pagina Grafici: i grafici della dashboard in grande e con più dettaglio, per un periodo
a scelta (YTD, ultimi 5 anni, totale o un anno singolo):

  Flusso / Composizione — Sankey entrate -> risparmio/spese -> categorie e lo stesso albero
                          come sunburst interattivo
  Andamento             — barre mensili (spese, risparmio, entrate/uscite) con medie e dettagli
  Cumulate              — totale / necessità / extra / risparmio contro anno precedente e target
  Extra, Risparmio      — anello del ritmo (dell'anno scelto) con la spesa extra per categoria e il
                          risparmio cumulato contro l'obiettivo

Le viste con un anello o con le cumulate usano l'anno scelto (o l'anno in corso per YTD e per i
periodi su più anni); i budget e i target sono quelli di quell'anno (tabella `budgets`).
"""
from flask import Blueprint, render_template, request, jsonify
import calendar, json, sys, os
from collections import defaultdict
from datetime import datetime, date

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from db import finance_db
from helpers import q, all_years, categories, budget_for
from palette import ESSENTIAL, EXTRA, SANKEY
from blueprints.dashboard import _ritmo_data, _panel_savings_goal, _slope

grafici_bp = Blueprint('grafici', __name__)


def _period(arg, years, today):
    """(chiave, etichetta, data inizio, data fine) dal parametro 'periodo':
    'ytd' | '5y' | 'all' | un anno a 4 cifre presente nei dati."""
    end = today.strftime('%Y-%m-%d')
    if arg in years:
        return arg, arg, f"{arg}-01-01", f"{arg}-12-31"
    if arg == '5y':
        first = max(today.year - 4, int(years[0]))
        return '5y', f"Ultimi 5 anni ({first}–{today.year})", f"{first}-01-01", end
    if arg == 'all':
        return 'all', f"Totale ({years[0]}–{years[-1]})", f"{years[0]}-01-01", '9999-12-31'
    return 'ytd', f"YTD {today.year}", f"{today.year}-01-01", end


VIEWS = ('flusso', 'composizione', 'andamento', 'cumulate', 'extra', 'risparmio')


def _ym_range(a, b):
    """['YYYY-MM', ...] da a a b inclusi."""
    out, y, m = [], int(a[:4]), int(a[5:7])
    while (y, m) <= (int(b[:4]), int(b[5:7])):
        out.append(f"{y}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


@grafici_bp.route('/grafici')
def index():
    today = datetime.today()
    with finance_db() as conn:
        years = all_years(conn)
        if not years:
            return render_template('grafici.html', empty=True)
        key, label, d0, d1 = _period(request.args.get('periodo', 'ytd'), years, today)

        total_inc = q(conn, "SELECT COALESCE(SUM(euro),0) FROM incomes "
                            "WHERE user_id=1 AND date BETWEEN ? AND ?", (d0, d1))[0][0]
        cat_rows = q(conn, """
            SELECT c.category, c.type, SUM(e.euro)
            FROM expenses e JOIN category c ON e.category=c.category COLLATE NOCASE
            WHERE e.user_id=1 AND e.date BETWEEN ? AND ?
            GROUP BY c.category, c.type ORDER BY 3 DESC""", (d0, d1))

        # ── Dati delle viste "dashboard in grande" ───────────────────────────
        first = conn.execute("SELECT MIN(date) FROM (SELECT date FROM incomes WHERE user_id=1 "
                             "UNION SELECT date FROM expenses WHERE user_id=1)").fetchone()[0]
        months = _ym_range(max(d0[:7], (first or f"{years[0]}-01-01")[:7]), min(d1[:7], today.strftime('%Y-%m')))
        inc_m = dict(q(conn, "SELECT strftime('%Y-%m', date), SUM(euro) FROM incomes "
                             "WHERE user_id=1 AND date BETWEEN ? AND ? GROUP BY 1", (d0, d1)))
        ess_m, ext_m = {}, {}
        for ym, ctype, tot in q(conn, """
                SELECT strftime('%Y-%m', e.date), c.type, SUM(e.euro) FROM expenses e
                JOIN category c ON e.category=c.category COLLATE NOCASE
                WHERE e.user_id=1 AND e.date BETWEEN ? AND ? GROUP BY 1, 2""", (d0, d1)):
            (ess_m if ctype == 'essential' else ext_m)[ym] = tot
        andamento = {'labels': months,
                     'income': [round(inc_m.get(m, 0), 2) for m in months],
                     'essential': [round(ess_m.get(m, 0), 2) for m in months],
                     'extra': [round(ext_m.get(m, 0), 2) for m in months]}

        # Anelli e cumulate: per l'anno scelto (un anno singolo) oppure per l'anno in corso.
        cum_year = int(key) if key in years else today.year
        ref = today.date() if cum_year == today.year else date(cum_year, 12, 31)
        budgets = {'ess': budget_for(conn, cum_year, 'essential'),
                   'ext': budget_for(conn, cum_year, 'extra'),
                   'sav': budget_for(conn, cum_year, 'savings')}
        ring = {'extra': _ritmo_data(conn, ref), 'goal': _panel_savings_goal(conn, ref)}
        cats_all = categories(conn)

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

    view = request.args.get('vista', 'flusso')
    return render_template('grafici.html', empty=False, years=years, key=key, label=label,
        view=view if view in VIEWS else 'flusso',
        andamento=json.dumps(andamento), cum_year=cum_year, cum_today_doy=ref.timetuple().tm_yday,
        cum_days=366 if calendar.isleap(cum_year) else 365, cum_years=[int(y) for y in years],
        cats_ess=[c for c, t in cats_all if t == 'essential'], cats_ext=[c for c, t in cats_all if t == 'extra'],
        budgets=json.dumps(budgets), ring=json.dumps(ring),
        extra_cats=json.dumps([[c, round(t, 2)] for c, ctype, t in cat_rows if ctype == 'extra']),
        sankey_data=json.dumps({'nodes': nodes, 'node_colors': n_col,
                                'sources': src, 'targets': tgt,
                                'values': val, 'link_colors': l_col}),
        sunburst_available=sun_available,
        sunburst_data=json.dumps({'ids': sun_ids, 'labels': sun_labels,
                                  'parents': sun_parents, 'values': sun_values,
                                  'colors': sun_colors}))


# ── Cumulata: dati per l'anno scelto, con confronto e categoria a piacere ─────

def _doy(d):
    return datetime.strptime(d, '%Y-%m-%d').timetuple().tm_yday


@grafici_bp.route('/grafici/cumulata.json')
def cumulata():
    """Cumulata giornaliera per `anno` (totale / necessità / extra / risparmio, oppure una singola
    categoria con `cat`), confrontata con `conf`: ''/assente = anno precedente, 'none' = nessun
    confronto, oppure un anno qualsiasi. Il target è il budget dell'anno scelto (nessuno per una
    singola categoria). Il delta confronta la pendenza delle due rette sulla stessa finestra
    (1 gennaio → oggi per l'anno in corso, anno intero per quelli passati)."""
    today = datetime.today()
    with finance_db() as conn:
        years = all_years(conn)
        year = request.args.get('anno', type=int)
        if str(year) not in years:
            year = today.year
        conf = request.args.get('conf', '')
        cmp_year = None if conf == 'none' else (int(conf) if conf.isdigit() and int(conf) != year else year - 1)
        view = request.args.get('vista', 'tot')
        if view not in ('tot', 'ess', 'ext', 'sav'):
            view = 'tot'
        cat = request.args.get('cat', '').strip()
        cat_type = dict(categories(conn)).get(cat, '') if cat else ''
        if cat and not cat_type:
            cat = ''

        wanted = [y for y in (cmp_year, year) if y]
        ph = ','.join('?' * len(wanted))
        ys = tuple(str(y) for y in wanted)
        rows = q(conn, f"""
            SELECT e.date, e.euro, COALESCE(c.type, ''), e.category FROM expenses e
            LEFT JOIN category c ON e.category=c.category COLLATE NOCASE
            WHERE e.user_id=1 AND strftime('%Y', e.date) IN ({ph})""", ys)
        maps = {y: defaultdict(float) for y in wanted}
        for d, e, t, c in rows:
            y, day = int(d[:4]), _doy(d)
            if cat:
                if c.lower() == cat.lower():
                    maps[y][day] += e
            elif view == 'tot' or (view == 'ess' and t == 'essential') or (view == 'ext' and t == 'extra'):
                maps[y][day] += e
            elif view == 'sav':
                maps[y][day] -= e
        if view == 'sav' and not cat:
            for d, e in q(conn, f"SELECT date, euro FROM incomes WHERE user_id=1 AND strftime('%Y', date) IN ({ph})", ys):
                maps[int(d[:4])][_doy(d)] += e

        target = 0.0
        if not cat:
            ess, ext = budget_for(conn, year, 'essential'), budget_for(conn, year, 'extra')
            target = {'tot': ess + ext, 'ess': ess, 'ext': ext, 'sav': budget_for(conn, year, 'savings')}[view]

    ref = today.date() if year == today.year else date(year, 12, 31)
    n_days = ref.timetuple().tm_yday
    series = []
    for y in wanted:
        cumul, xs, ys_ = 0.0, [], []
        for day in sorted(maps[y]):
            cumul += maps[y][day]
            xs.append(day); ys_.append(round(cumul, 2))
        series.append({'year': str(y), 'x': xs, 'y': ys_})

    delta = None
    if cmp_year:
        s_cur, s_cmp = _slope(maps[year], n_days), _slope(maps[cmp_year], n_days)
        if s_cur is not None and s_cmp and s_cmp > 0:
            delta = {'pct': round((s_cur / s_cmp - 1) * 100, 1), 'cur': round(s_cur * 30, 2),
                     'cmp': round(s_cmp * 30, 2), 'cmp_year': cmp_year}
    kind = {'essential': 'ess', 'extra': 'ext'}.get(cat_type, view)
    return jsonify(year=year, cmp_year=cmp_year, series=series, target=round(target, 2), kind=kind, delta=delta,
                   total=round(sum(maps[year].values()), 2), today_doy=n_days,
                   days=366 if calendar.isleap(year) else 365)

