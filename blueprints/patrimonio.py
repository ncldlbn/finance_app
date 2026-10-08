"""Pagina Patrimonio: tabella e grafico dei posti che l'utente ha reso visibili (vedi wealth.py)."""
import json
import sys
import os

from flask import Blueprint, render_template, request, flash, redirect, url_for

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import wealth
from db import finance_db
from palette import P
from validators import int_arg, parse_amount, parse_int, YEAR_MIN, YEAR_MAX

patrimonio_bp = Blueprint('patrimonio', __name__)

MESI_FULL = ['', 'Gennaio', 'Febbraio', 'Marzo', 'Aprile', 'Maggio', 'Giugno',
             'Luglio', 'Agosto', 'Settembre', 'Ottobre', 'Novembre', 'Dicembre']
PAGE_SIZE = 100


def _color(group):
    return P['patrimonio'][group['color']]


@patrimonio_bp.route('/patrimonio')
def index():
    with finance_db() as conn:
        cfg = wealth.config(conn)
        months = wealth.months(conn)                                  # dal più recente
    counts = cfg['counts']

    shown_groups = [g for g in cfg['groups'] if g['shown']]
    # Colonne: i posti visibili, più quelli nascosti ma con valori? No: nascosti = non mostrati (si sommano nel gruppo).
    cols = [dict(code=s['code'], label=s['label'], color=_color(g), group=g['label'])
            for g in shown_groups for s in g['slots'] if s['visible']]

    rows = []
    for m in months:
        sums = wealth.group_sums(m['values'])
        rows.append(dict(anno=m['anno'], mese=m['mese'], vals=m['values'], sums=sums,
                         total=round(wealth.total(sums, counts), 2)))
    for i, r in enumerate(rows):
        r['variazione'] = round(r['total'] - rows[i + 1]['total'], 2) if i < len(rows) - 1 else None

    # Grafico: un'area per gruppo mostrato (le passività sotto lo zero), in ordine cronologico.
    asc = list(reversed(rows))
    chart_data = json.dumps({
        'labels': [f"{r['anno']}-{r['mese']:02d}" for r in asc],
        'groups': [dict(key=g['key'], label=g['label'], color=_color(g), sign=g['sign'], counts=g['counts'],
                        values=[round(r['sums'][g['key']], 2) for r in asc]) for g in shown_groups],
    })

    # Campi del modulo di modifica: i posti visibili più quelli nascosti che hanno almeno un valore.
    used = {code for r in rows for code in r['vals']}
    edit_slots = [dict(code=s['code'], label=s['label'], hidden=not s['visible'])
                  for g in cfg['groups'] for s in g['slots'] if s['visible'] or s['code'] in used]

    page = int_arg('page', 1)
    total = len(rows)
    pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    page = min(page, pages)
    rows_page = rows[(page - 1) * PAGE_SIZE: page * PAGE_SIZE]
    year_counts = {}
    for r in rows_page:
        year_counts[r['anno']] = year_counts.get(r['anno'], 0) + 1

    total_label = next((lab for k, lab in wealth.PRESET_LABELS.items() if {g for g, c in counts.items() if c} == wealth.PRESETS[k]), 'Totale personalizzato')
    return render_template('patrimonio.html', rows=rows_page, year_counts=year_counts, chart_data=chart_data, cols=cols,
                           shown_groups=shown_groups, edit_slots=edit_slots, mesi_full=MESI_FULL, total_label=total_label,
                           page=page, pages=pages, total=total, PAGE_SIZE=PAGE_SIZE)


def _form_values(slots):
    """Importi inviati dal modulo per i posti dati: vuoto = nessun valore; sono ammessi i negativi."""
    out = {}
    for code, label in slots:
        raw = (request.form.get(code) or '').strip()
        if raw != '':
            out[code] = parse_amount(raw, code, label)
    return out


@patrimonio_bp.route('/patrimonio/<int:anno>/<int:mese>/edit', methods=['POST'])
def edit(anno, mese):
    anno = parse_int(anno, 'anno', 'Anno', YEAR_MIN, YEAR_MAX)
    mese = parse_int(mese, 'mese', 'Mese', 1, 12)
    with finance_db() as conn:
        cfg = wealth.config(conn)
        have = {r[0] for r in conn.execute('SELECT slot FROM wealth_values WHERE user_id=current_uid() AND anno=? AND mese=?', (anno, mese))}
        if not have:
            flash('Mese non trovato.', 'error')
            return redirect(url_for('patrimonio.index'))
        editable = [(c, s['label']) for c, s in cfg['slots'].items() if s['visible'] or c in have]
        values = _form_values(editable)
        for code, _ in editable:
            if code in values:
                conn.execute('INSERT INTO wealth_values (user_id, anno, mese, slot, value) VALUES (current_uid(),?,?,?,?) '
                             'ON CONFLICT(user_id, anno, mese, slot) DO UPDATE SET value=excluded.value', (anno, mese, code, values[code]))
            else:
                conn.execute('DELETE FROM wealth_values WHERE user_id=current_uid() AND anno=? AND mese=? AND slot=?', (anno, mese, code))
        conn.commit()
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return ('', 204)
    flash('Patrimonio aggiornato.', 'success')
    return redirect(url_for('patrimonio.index'))


@patrimonio_bp.route('/patrimonio/<int:anno>/<int:mese>/delete', methods=['POST'])
def delete(anno, mese):
    with finance_db() as conn:
        conn.execute('DELETE FROM wealth_values WHERE user_id=current_uid() AND anno=? AND mese=?', (anno, mese))
        conn.commit()
    flash('Mese eliminato.', 'success')
    return redirect(url_for('patrimonio.index'))
