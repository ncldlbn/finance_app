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
    'directa':  'Directa',
    'deposito': 'Deposito',
    'obblig':   'Obbligazioni',
    'etf_etc':  'ETF / ETC',
    'debito':   'Debito',
    'credito':  'Credito',
    'cauzioni': 'Cauzioni',
    'tfr':      'TFR',
    'fon_te':   'Fon.Te.',
}

# Component definitions for KPI boxes and chart
COMPONENTS = [
    ('liquidita',  'Liquidità',             'BCC + BBVA + Directa'),
    ('emergenza',  'Fondo emergenza',        'Deposito'),
    ('breve',      'Breve termine',          'Obbligazioni'),
    ('lungo',      'Lungo termine',          'ETF / ETC'),
    ('previdenza', 'Pensione complementare', 'TFR + Fon.Te.'),
]


def calc_derived(row):
    liquidita  = row['bcc'] + row['bbva'] + row['directa']
    emergenza  = row['deposito']
    breve      = row['obblig']
    lungo      = row['etf_etc']
    previdenza = row['tfr'] + row['fon_te']
    totale     = liquidita + emergenza + breve + lungo
    return dict(liquidita=liquidita, emergenza=emergenza, breve=breve,
                lungo=lungo, previdenza=previdenza, totale=totale)


def get_all_rows():
    with finance_db() as conn:
        rows = conn.execute(
            f"SELECT id, anno, mese, {','.join(FIELDS)} FROM patrimonio ORDER BY anno DESC, mese DESC"
        ).fetchall()
    cols   = ['id', 'anno', 'mese'] + FIELDS
    result = []
    for r in rows:
        d = dict(zip(cols, r))
        d.update(calc_derived(d))
        result.append(d)
    return result


@patrimonio_bp.route('/patrimonio', methods=['GET'])
def index():
    today = datetime.today()
    rows  = get_all_rows()

    chart_rows = list(reversed(rows))
    labels     = [f"{r['anno']}-{r['mese']:02d}" for r in chart_rows]

    chart_data = json.dumps({
        'labels':     labels,
        'liquidita':  [round(r['liquidita'],  2) for r in chart_rows],
        'emergenza':  [round(r['emergenza'],  2) for r in chart_rows],
        'breve':      [round(r['breve'],      2) for r in chart_rows],
        'lungo':      [round(r['lungo'],      2) for r in chart_rows],
        'previdenza': [round(r['previdenza'], 2) for r in chart_rows],
        'totale':     [round(r['totale'],     2) for r in chart_rows],
    })

    for i, r in enumerate(rows):
        r['variazione'] = r['totale'] - rows[i + 1]['totale'] if i < len(rows) - 1 else None

    mesi_it = ['', 'Gen', 'Feb', 'Mar', 'Apr', 'Mag', 'Giu', 'Lug', 'Ago', 'Set', 'Ott', 'Nov', 'Dic']

    PAGE_SIZE = 10
    page      = max(1, int(request.args.get('page', 1)))
    total     = len(rows)
    pages     = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    page      = min(page, pages)
    rows_page = rows[(page - 1) * PAGE_SIZE : page * PAGE_SIZE]

    return render_template('patrimonio.html',
        rows=rows_page, chart_data=chart_data,
        fields=FIELDS, labels=LABELS, components=COMPONENTS,
        mesi_it=mesi_it,
        anni_range=list(range(today.year - 5, today.year + 2)),
        today=today,
        page=page, pages=pages, total=total, PAGE_SIZE=PAGE_SIZE,
    )


@patrimonio_bp.route('/patrimonio/add', methods=['POST'])
def add():
    anno = int(request.form.get('anno', datetime.today().year))
    mese = int(request.form.get('mese', datetime.today().month))
    vals = _parse_form()

    with finance_db() as conn:
        if conn.execute("SELECT id FROM patrimonio WHERE anno=? AND mese=?", (anno, mese)).fetchone():
            flash(f'Esiste già un record per {mese}/{anno}. Modificalo dalla tabella.', 'error')
            return redirect(url_for('patrimonio.index'))
        conn.execute(
            f"INSERT INTO patrimonio (anno, mese, {', '.join(FIELDS)}) VALUES (?,?,{','.join(['?']*len(FIELDS))})",
            [anno, mese] + [vals[f] for f in FIELDS])
        conn.commit()
    flash('Mese aggiunto.', 'success')
    return redirect(url_for('patrimonio.index'))


@patrimonio_bp.route('/patrimonio/<int:pid>/edit', methods=['POST'])
def edit(pid):
    vals = _parse_form()
    with finance_db() as conn:
        conn.execute(
            f"UPDATE patrimonio SET {', '.join(f+'=?' for f in FIELDS)} WHERE id=?",
            [vals[f] for f in FIELDS] + [pid])
        conn.commit()
    flash('Patrimonio aggiornato.', 'success')
    return redirect(url_for('patrimonio.index'))


@patrimonio_bp.route('/patrimonio/<int:pid>/delete', methods=['POST'])
def delete(pid):
    with finance_db() as conn:
        conn.execute("DELETE FROM patrimonio WHERE id=?", (pid,))
        conn.commit()
    flash('Voce eliminata.', 'success')
    return redirect(url_for('patrimonio.index'))


# ── keep old /patrimonio/save for backward compat ────────────────────────────
@patrimonio_bp.route('/patrimonio/save', methods=['POST'])
def save():
    anno = int(request.form['anno'])
    mese = int(request.form['mese'])
    vals = _parse_form()
    with finance_db() as conn:
        existing = conn.execute(
            "SELECT id FROM patrimonio WHERE anno=? AND mese=?", (anno, mese)
        ).fetchone()
        if existing:
            conn.execute(
                f"UPDATE patrimonio SET {', '.join(f+'=?' for f in FIELDS)} WHERE anno=? AND mese=?",
                [vals[f] for f in FIELDS] + [anno, mese])
            flash('Patrimonio aggiornato.', 'success')
        else:
            conn.execute(
                f"INSERT INTO patrimonio (anno, mese, {', '.join(FIELDS)}) VALUES (?,?,{','.join(['?']*len(FIELDS))})",
                [anno, mese] + [vals[f] for f in FIELDS])
            flash('Patrimonio salvato.', 'success')
        conn.commit()
    return redirect(url_for('patrimonio.index'))


def _parse_form():
    vals = {}
    for f in FIELDS:
        raw = request.form.get(f, '0').replace(',', '.').strip() or '0'
        try:
            vals[f] = float(raw)
        except ValueError:
            vals[f] = 0.0
    return vals
