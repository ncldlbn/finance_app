from flask import Blueprint, render_template, request, flash, redirect, url_for
import json, sys, os
from datetime import datetime
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from db import finance_db

patrimonio_bp = Blueprint('patrimonio', __name__)

FIELDS = ['bcc', 'bbva', 'directa', 'deposito', 'obblig', 'etf_etc', 'debito', 'credito', 'cauzioni', 'tfr', 'fon_te']
LABELS = {
    'bcc':      'BCC',
    'bbva':     'BBVA',
    'directa':  'DIRECTA',
    'deposito': 'Deposito',
    'obblig':   'Obbligazioni',
    'etf_etc':  'ETF / ETC',
    'debito':   'Debito',
    'credito':  'Credito',
    'cauzioni': 'Cauzioni',
    'tfr':      'TFR',
    'fon_te':   'Fon.Te.',
}
GROUPS = {
    'Liquidità':     ['bcc', 'bbva', 'directa'],
    'Breve termine': ['deposito', 'obblig'],
    'Lungo termine': ['etf_etc'],
    'Previdenza':    ['tfr', 'fon_te'],
    'Altro':         ['cauzioni', 'credito', 'debito'],
}


def calc_derived(row):
    liquidita    = row['bcc'] + row['bbva'] + row['directa']
    breve        = liquidita + row['deposito'] + row['obblig']
    lungo        = row['etf_etc']
    previdenza   = row['tfr'] + row['fon_te']
    altri_attivi = row['cauzioni'] + row['credito']
    totale       = breve + lungo + previdenza + altri_attivi - row['debito']
    return dict(liquidita=liquidita, breve=breve, lungo=lungo, previdenza=previdenza, totale=totale)


def get_all_rows():
    with finance_db() as conn:
        rows = conn.execute(
            f"SELECT id, anno, mese, {','.join(FIELDS)}, note FROM patrimonio ORDER BY anno DESC, mese DESC"
        ).fetchall()
    cols   = ['id', 'anno', 'mese'] + FIELDS + ['note']
    result = []
    for r in rows:
        d = dict(zip(cols, r))
        d.update(calc_derived(d))
        result.append(d)
    return result


def get_row(anno, mese):
    with finance_db() as conn:
        r = conn.execute(
            f"SELECT id, anno, mese, {','.join(FIELDS)}, note FROM patrimonio WHERE anno=? AND mese=?",
            (anno, mese)
        ).fetchone()
    if not r:
        return None
    cols = ['id', 'anno', 'mese'] + FIELDS + ['note']
    d = dict(zip(cols, r))
    d.update(calc_derived(d))
    return d


@patrimonio_bp.route('/patrimonio', methods=['GET'])
def index():
    today = datetime.today()
    rows  = get_all_rows()

    chart_rows = list(reversed(rows))
    labels     = [f"{r['anno']}-{r['mese']:02d}" for r in chart_rows]

    chart_data = json.dumps({
        'labels':     labels,
        'liquidita':  [round(r['liquidita'], 2)  for r in chart_rows],
        'breve':      [round(r['breve'], 2)       for r in chart_rows],
        'lungo':      [round(r['lungo'], 2)       for r in chart_rows],
        'previdenza': [round(r['previdenza'], 2)  for r in chart_rows],
        'totale':     [round(r['totale'], 2)      for r in chart_rows],
        'debito':     [round(r['debito'], 2)      for r in chart_rows],
    })

    for i, r in enumerate(rows):
        r['variazione'] = r['totale'] - rows[i + 1]['totale'] if i < len(rows) - 1 else None

    edit_anno = int(request.args.get('edit_anno', today.year))
    edit_mese = int(request.args.get('edit_mese', today.month))
    edit_row  = get_row(edit_anno, edit_mese) or {}

    mesi_it = ['', 'Gen', 'Feb', 'Mar', 'Apr', 'Mag', 'Giu', 'Lug', 'Ago', 'Set', 'Ott', 'Nov', 'Dic']

    return render_template('patrimonio.html',
        rows=rows, chart_data=chart_data,
        fields=FIELDS, labels=LABELS, groups=GROUPS,
        edit_anno=edit_anno, edit_mese=edit_mese, edit_row=edit_row,
        mesi_it=mesi_it,
        anni_range=list(range(today.year - 5, today.year + 2)),
        today=today,
    )


@patrimonio_bp.route('/patrimonio/save', methods=['POST'])
def save():
    anno = int(request.form['anno'])
    mese = int(request.form['mese'])
    vals = {}
    for f in FIELDS:
        raw = request.form.get(f, '0').replace(',', '.').strip() or '0'
        try:
            vals[f] = float(raw)
        except ValueError:
            vals[f] = 0.0
    note = request.form.get('note', '')

    with finance_db() as conn:
        existing = conn.execute(
            "SELECT id FROM patrimonio WHERE anno=? AND mese=?", (anno, mese)
        ).fetchone()
        if existing:
            conn.execute(
                f"UPDATE patrimonio SET {', '.join(f+'=?' for f in FIELDS)}, note=? WHERE anno=? AND mese=?",
                [vals[f] for f in FIELDS] + [note, anno, mese])
            flash('Patrimonio aggiornato.', 'success')
        else:
            conn.execute(
                f"INSERT INTO patrimonio (anno, mese, {', '.join(FIELDS)}, note) VALUES (?,?,{','.join(['?']*len(FIELDS))},?)",
                [anno, mese] + [vals[f] for f in FIELDS] + [note])
            flash('Patrimonio salvato.', 'success')
        conn.commit()
    return redirect(url_for('patrimonio.index', edit_anno=anno, edit_mese=mese))


@patrimonio_bp.route('/patrimonio/<int:pid>/delete', methods=['POST'])
def delete(pid):
    with finance_db() as conn:
        conn.execute("DELETE FROM patrimonio WHERE id=?", (pid,))
        conn.commit()
    flash('Voce eliminata.', 'success')
    return redirect(url_for('patrimonio.index'))
