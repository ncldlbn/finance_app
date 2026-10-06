"""Pagina Flusso: Sankey entrate -> risparmio/spese -> categorie, oppure la
stessa gerarchia come sunburst interattivo (vista Composizione), per un
periodo a scelta: YTD, ultimi 5 anni, totale o un anno singolo."""
from flask import Blueprint, render_template, request
import json, sys, os
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from db import finance_db
from helpers import q, all_years
from palette import ESSENTIAL, EXTRA, SANKEY

flusso_bp = Blueprint('flusso', __name__)


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


@flusso_bp.route('/flusso')
def index():
    today = datetime.today()
    with finance_db() as conn:
        years = all_years(conn)
        if not years:
            return render_template('flusso.html', empty=True)
        key, label, d0, d1 = _period(request.args.get('periodo', 'ytd'), years, today)

        total_inc = q(conn, "SELECT COALESCE(SUM(euro),0) FROM incomes "
                            "WHERE user_id=1 AND date BETWEEN ? AND ?", (d0, d1))[0][0]
        cat_rows = q(conn, """
            SELECT c.category, c.type, SUM(e.euro)
            FROM expenses e JOIN category c ON e.category=c.category COLLATE NOCASE
            WHERE e.user_id=1 AND e.date BETWEEN ? AND ?
            GROUP BY c.category, c.type ORDER BY 3 DESC""", (d0, d1))

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

    return render_template('flusso.html', empty=False, years=years, key=key, label=label,
        sankey_data=json.dumps({'nodes': nodes, 'node_colors': n_col,
                                'sources': src, 'targets': tgt,
                                'values': val, 'link_colors': l_col}),
        sunburst_available=sun_available,
        sunburst_data=json.dumps({'ids': sun_ids, 'labels': sun_labels,
                                  'parents': sun_parents, 'values': sun_values,
                                  'colors': sun_colors}))
