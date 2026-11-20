"""Dashboard: pagina di atterraggio dell'app (route '/').

Due viste dello stesso periodo, scelte in alto: **Mese** (`?vista=mese&mese=2026-11`) e **Anno**
(`?vista=anno&anno=2026`). Senza parametri: il mese in corso. Si possono consultare i periodi passati,
dal primo movimento a oggi; un periodo fuori da questi limiti viene riportato dentro.

Sei pannelli in griglia 3×2, uguali nelle due viste:
    Bilancio (con budget extra e obiettivo di risparmio) · Composizione · Patrimonio
    Mese per mese · Categorie rispetto al riferimento · Cumulata
"""
from flask import Blueprint, render_template, request
import sys, os, calendar
from datetime import date, datetime
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from db import finance_db
from helpers import q, budget_for, categories, MESI_IT, MESI_IT_FULL
from palette import ESSENTIAL, EXTRA, SANKEY
import wealth

dashboard_bp = Blueprint('dashboard', __name__)


# ── Periodo ──────────────────────────────────────────────────────────────────

def _ym_index(y, m):
    return y * 12 + (m - 1)


def _ym_from_index(i):
    return i // 12, i % 12 + 1


def _month_end(y, m):
    return date(y, m, calendar.monthrange(y, m)[1])


def _same_day_prev_year(d):
    """Lo stesso giorno dell'anno prima (il 29 febbraio diventa il 28)."""
    try:
        return d.replace(year=d.year - 1)
    except ValueError:
        return d.replace(year=d.year - 1, day=28)


def _period(conn, args, today):
    """Il periodo da mostrare, già riportato tra il primo movimento e oggi."""
    first = q(conn, """
        SELECT MIN(d) FROM (
            SELECT MIN(date) AS d FROM incomes WHERE user_id=current_uid()
            UNION ALL
            SELECT MIN(date) FROM expenses WHERE user_id=current_uid())""")[0][0]
    now_i = _ym_index(today.year, today.month)
    first_i = _ym_index(int(first[:4]), int(first[5:7])) if first else now_i
    first_i = min(first_i, now_i)

    vista = 'anno' if args.get('vista') == 'anno' else 'mese'
    if vista == 'mese':
        sel_i = now_i
        raw = args.get('mese', '')
        try:
            y, m = int(raw[:4]), int(raw[5:7])
            if raw[4] == '-' and 1 <= m <= 12:
                sel_i = _ym_index(y, m)
        except (ValueError, IndexError):
            pass
        sel_i = max(first_i, min(sel_i, now_i))
        y, m = _ym_from_index(sel_i)
        start, end = date(y, m, 1), _month_end(y, m)
        current = sel_i == now_i
        prev_i, next_i = sel_i - 1, sel_i + 1
        p = dict(label=f"{MESI_IT_FULL[m]} {y}",
                 sub=f"giorno {today.day} di {end.day}" if current else 'mese chiuso',
                 prev=f"{_ym_from_index(prev_i)[0]}-{_ym_from_index(prev_i)[1]:02d}" if prev_i >= first_i else None,
                 next=f"{_ym_from_index(next_i)[0]}-{_ym_from_index(next_i)[1]:02d}" if next_i <= now_i else None,
                 other_year=y)
    else:
        y = today.year
        try:
            y = int(args.get('anno', today.year))
        except ValueError:
            pass
        first_y = _ym_from_index(first_i)[0]
        y = max(first_y, min(y, today.year))
        m = 12 if y < today.year else today.month
        start, end = date(y, 1, 1), date(y, 12, 31)
        current = y == today.year
        p = dict(label=str(y),
                 sub=f"fino al {today.day} {MESI_IT_FULL[today.month].lower()}" if current else 'anno chiuso',
                 prev=str(y - 1) if y - 1 >= first_y else None,
                 next=str(y + 1) if y + 1 <= today.year else None,
                 # passando alla vista Mese: il mese in corso per l'anno corrente, dicembre per uno passato
                 other_month=f"{y}-{m:02d}")
    ref = min(today.date() if isinstance(today, datetime) else today, end)

    # Scelta del periodo: mesi di ogni anno disponibile (per la griglia del selettore) e anni.
    first_y, first_m = _ym_from_index(first_i)
    years = list(range(today.year, first_y - 1, -1))
    picker = {yy: [dict(label=MESI_IT[mm - 1], value=f"{yy}-{mm:02d}",
                        off=not (first_i <= _ym_index(yy, mm) <= now_i)) for mm in range(1, 13)] for yy in years}
    p.update(vista=vista, year=y, month=m, start=start, end=end, ref=ref, current=current,
             first_i=first_i, years=years, picker=picker,
             value=f"{y}-{m:02d}" if vista == 'mese' else str(y))
    return p


def _span(a, b):
    return a.strftime('%Y-%m-%d'), b.strftime('%Y-%m-%d')


# ── Somme di base ────────────────────────────────────────────────────────────

def _totals(conn, start, end):
    """Entrate, necessità, extra e spese totali tra due date (incluse).
    Le spese totali contano anche quelle senza tipo, così il risparmio non dipende dalle categorie."""
    ss, se = _span(start, end)
    inc = q(conn, "SELECT COALESCE(SUM(euro),0) FROM incomes WHERE user_id=current_uid() AND date BETWEEN ? AND ?",
            (ss, se))[0][0]
    tot = q(conn, "SELECT COALESCE(SUM(euro),0) FROM expenses WHERE user_id=current_uid() AND date BETWEEN ? AND ?",
            (ss, se))[0][0]
    split = dict(q(conn, """
        SELECT c.type, SUM(e.euro) FROM expenses e
        JOIN category c ON e.category=c.category COLLATE NOCASE AND c.user_id=e.user_id
        WHERE e.user_id=current_uid() AND e.date BETWEEN ? AND ? GROUP BY c.type""", (ss, se)))
    return dict(inc=inc, nec=split.get('essential', 0), ext=split.get('extra', 0), out=tot, sav=inc - tot)


def _monthly(conn, first_i, n):
    """Totali di `n` mesi consecutivi dal mese con indice `first_i`: [{ym, inc, nec, ext, out, sav}]."""
    y0, m0 = _ym_from_index(first_i)
    y1, m1 = _ym_from_index(first_i + n - 1)
    ss, se = _span(date(y0, m0, 1), _month_end(y1, m1))
    inc = dict(q(conn, "SELECT strftime('%Y-%m',date), SUM(euro) FROM incomes "
                       "WHERE user_id=current_uid() AND date BETWEEN ? AND ? GROUP BY 1", (ss, se)))
    out = dict(q(conn, "SELECT strftime('%Y-%m',date), SUM(euro) FROM expenses "
                       "WHERE user_id=current_uid() AND date BETWEEN ? AND ? GROUP BY 1", (ss, se)))
    nec, ext = defaultdict(float), defaultdict(float)
    for ym, ctype, tot in q(conn, """
            SELECT strftime('%Y-%m',e.date), c.type, SUM(e.euro)
            FROM expenses e JOIN category c ON e.category=c.category COLLATE NOCASE AND c.user_id=e.user_id
            WHERE e.user_id=current_uid() AND e.date BETWEEN ? AND ? GROUP BY 1,2""", (ss, se)):
        (nec if ctype == 'essential' else ext)[ym] += tot
    rows = []
    for i in range(first_i, first_i + n):
        y, m = _ym_from_index(i)
        ym = f"{y}-{m:02d}"
        rows.append(dict(ym=ym, y=y, m=m, inc=inc.get(ym, 0), nec=nec.get(ym, 0), ext=ext.get(ym, 0),
                         out=out.get(ym, 0), sav=inc.get(ym, 0) - out.get(ym, 0)))
    return rows


def _ref_window(p):
    """Mesi di riferimento della vista Mese: i 12 precedenti, ma non prima del primo movimento.
    (primo indice, numero di mesi); numero 0 = nessun riferimento."""
    sel_i = _ym_index(p['year'], p['month'])
    first = max(sel_i - 12, p['first_i'])
    return first, max(sel_i - first, 0)


def _eur(v):
    return '€ ' + f"{abs(v):,.0f}".replace(',', '.')


def _pct(v, base):
    return f"{round(abs(v) / base * 100)}%" if base else ''


# ── Pannello: Bilancio ───────────────────────────────────────────────────────

def _panel_bilancio(conn, p):
    """Una riga per voce (entrate, uscite, necessità, extra, risparmio), tutte sulla scala delle entrate.
    Extra: barra chiara fino al budget; risparmio: barra chiara fino all'obiettivo. Nella vista Anno
    dell'anno in corso una tacca segna il ritmo di oggi. I dettagli compaiono passando sopra la riga."""
    t = _totals(conn, p['start'], p['end'])
    mese = p['vista'] == 'mese'
    budget = budget_for(conn, p['year'], 'extra') / (12 if mese else 1)
    goal = budget_for(conn, p['year'], 'savings') / (12 if mese else 1)
    pace = None
    if not mese and p['current']:
        yr_len = 366 if calendar.isleap(p['year']) else 365
        pace = p['ref'].timetuple().tm_yday / yr_len

    # Riferimenti per i dettagli: media dei 12 mesi precedenti (Mese) o stesso periodo dell'anno prima (Anno).
    if mese:
        w_first, w_n = _ref_window(p)
        ref_rows = _monthly(conn, w_first, w_n) if w_n else []
        avg = {k: sum(r[k] for r in ref_rows) / w_n for k in ('inc', 'out', 'nec', 'sav')} if w_n else None
        ref_txt = lambda k: f"Media degli ultimi {w_n} mesi: {_eur(avg[k])}" if avg else 'Nessun mese precedente da confrontare'
    else:
        prev = _totals(conn, date(p['year'] - 1, 1, 1), _same_day_prev_year(p['ref']))
        def ref_txt(k):
            if not prev[k]:
                return f"Nessun dato del {p['year'] - 1} da confrontare"
            d = (t[k] / prev[k] - 1) * 100
            return f"{'+' if d >= 0 else '−'}{abs(d):.1f}% sul {p['year'] - 1} nello stesso periodo".replace('.', ',')

    def ext_tip():
        if not budget:
            return ['Nessun budget extra impostato', 'Si imposta in Impostazioni › Budget']
        head = f"{_eur(t['ext'])} di {_eur(budget)} di budget"
        left = budget - t['ext']
        if pace is not None:
            d = t['ext'] - budget * pace
            return [head, f"{_eur(d)} {'sopra' if d > 0 else 'sotto'} il ritmo di oggi · "
                          + (f"restano {_eur(left)}" if left >= 0 else f"{_eur(left)} oltre il budget")]
        if mese and p['current']:
            days = p['end'].day - p['ref'].day
            if left < 0:
                return [head, f"{_eur(left)} oltre il budget del mese"]
            return [head, f"Restano {_eur(left)}" + (f" per {days} giorni" if days > 0 else ' fino a stasera')]
        return [head, f"{_eur(left)} {'sotto' if left >= 0 else 'oltre'} il budget"]

    def sav_tip():
        if not goal:
            return ['Nessun obiettivo di risparmio impostato', 'Si imposta in Impostazioni › Budget']
        head = f"{_eur(t['sav'])} di {_eur(goal)} di obiettivo" if t['sav'] >= 0 else f"−{_eur(t['sav'])}: spese oltre le entrate"
        miss = goal - t['sav']
        tail = f"Mancano {_eur(miss)}" if miss > 0 else f"Obiettivo superato di {_eur(miss)}"
        if pace is not None:
            d = t['sav'] - goal * pace
            tail = f"{_eur(d)} {'sopra' if d >= 0 else 'sotto'} il ritmo di oggi · " + tail.lower()
        return [head, tail]

    scale = max(t['inc'], t['out'], budget, goal, 1)
    w = lambda v: round(min(abs(v) / scale * 100, 100), 2)
    big, small = 'big', 'small'
    rows = [
        dict(key='inc', size=big, name='Entrate', value=_eur(t['inc']), pct='', w=w(t['inc']), color='var(--data-income)',
             tip=[_eur(t['inc']), ref_txt('inc')]),
        dict(key='out', size=big, name='Uscite', value=_eur(t['out']), pct=_pct(t['out'], t['inc']), w=w(t['out']),
             color='var(--data-expense)', tip=[f"{_eur(t['out'])}" + (f", il {_pct(t['out'], t['inc'])} delle entrate" if t['inc'] else ''), ref_txt('out')]),
        dict(key='nec', size=small, name='Necessità', value=_eur(t['nec']), pct=_pct(t['nec'], t['inc']), w=w(t['nec']),
             color='var(--data-essential)', tip=[f"{_eur(t['nec'])}" + (f", il {_pct(t['nec'], t['inc'])} delle entrate" if t['inc'] else ''), ref_txt('nec')]),
        dict(key='ext', size=small, name='Extra', value=_eur(t['ext']), pct=_pct(t['ext'], t['inc']), w=w(t['ext']),
             color='var(--data-extra)', ghost='var(--data-extra)', gw=w(budget) if budget else 0,
             pace=w(budget * pace) if (budget and pace is not None) else None, tip=ext_tip()),
        dict(key='sav', size=big, name='Risparmio', value=('+' if t['sav'] >= 0 else '−') + _eur(t['sav']),
             pct=_pct(t['sav'], t['inc']), w=w(t['sav']),
             color='var(--data-savings)' if t['sav'] >= 0 else 'var(--data-expense)',
             ghost='var(--data-savings)', gw=w(goal) if goal else 0,
             pace=w(goal * pace) if (goal and pace is not None) else None, tip=sav_tip()),
    ]
    return dict(rows=rows, has_goals=bool(budget or goal), has_pace=pace is not None and bool(budget or goal))


# ── Pannello: Composizione (ciambella) ───────────────────────────────────────

def _panel_sunburst(conn, start, end):
    ss, se = _span(start, end)
    cat_rows = q(conn, """
        SELECT e.category, c.type, SUM(e.euro) FROM expenses e
        JOIN category c ON e.category=c.category COLLATE NOCASE AND c.user_id=e.user_id
        WHERE e.user_id=current_uid() AND e.date BETWEEN ? AND ?
        GROUP BY e.category, c.type ORDER BY c.type, MIN(c.position), MIN(c.id)""", (ss, se))

    total_spe = sum(r[2] for r in cat_rows)
    nec = sum(r[2] for r in cat_rows if r[1] == 'essential')
    ext = sum(r[2] for r in cat_rows if r[1] == 'extra')
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
    return {'has_data': total_spe > 0,
            'sunburst_data': {'ids': ids, 'labels': labels, 'parents': parents, 'values': values, 'colors': colors}}


# ── Pannello: Patrimonio ─────────────────────────────────────────────────────

def _panel_patrimonio(conn, p):
    """Patrimonio a fine mese (regola del totale scelta in Impostazioni). Mese: i 12 mesi fino a quello
    scelto; Anno: i mesi dell'anno. Il numero grande è l'ultimo valore inserito entro la fine del periodo."""
    cfg = wealth.config(conn)
    totals = {(r['anno'], r['mese']): round(wealth.total(wealth.group_sums(r['values']), cfg['counts']), 2)
              for r in wealth.months(conn)}
    if p['vista'] == 'mese':
        sel_i = _ym_index(p['year'], p['month'])
        idx = list(range(sel_i - 11, sel_i + 1))
    else:
        idx = [_ym_index(p['year'], m) for m in range(1, 13)]
    end_i = _ym_index(p['year'], p['month'])
    known = sorted(i for i in (_ym_index(y, m) for y, m in totals) if i <= end_i)
    if not known:
        return dict(available=False)
    last_i = known[-1]
    last = totals[_ym_from_index(last_i)]
    # Variazione: dal mese prima (Mese) o dalla fine dell'anno precedente (Anno; se manca, dal primo mese dell'anno).
    if p['vista'] == 'mese':
        base_i = max((i for i in known if i < last_i), default=None)
        since = 'dal mese prima'
    else:
        dec_prev = _ym_index(p['year'] - 1, 12)
        base_i = dec_prev if dec_prev in known else min((i for i in known if i >= idx[0]), default=None)
        since = 'da inizio anno'
    delta = round(last - totals[_ym_from_index(base_i)], 2) if base_i is not None and base_i != last_i else None
    return dict(available=True, value=last, delta=delta, since=since,
                as_of=f"{MESI_IT_FULL[_ym_from_index(last_i)[1]].lower()} {_ym_from_index(last_i)[0]}",
                labels=[f"{_ym_from_index(i)[0]}-{_ym_from_index(i)[1]:02d}" for i in idx],
                values=[totals.get(_ym_from_index(i)) for i in idx])


# ── Pannello: Mese per mese ──────────────────────────────────────────────────

def _panel_mesi(conn, p):
    """Necessità + extra + risparmio per mese (l'altezza della barra è l'entrata); un risparmio negativo
    scende sotto lo zero. Sempre gennaio-dicembre dell'anno del periodo; nella vista Mese il mese scelto
    resta acceso e gli altri fanno da contesto."""
    rows = _monthly(conn, _ym_index(p['year'], 1), 12)
    selected = f"{p['year']}-{p['month']:02d}" if p['vista'] == 'mese' else None
    r2 = lambda v: round(v, 2)
    return dict(labels=[r['ym'] for r in rows], short=[f"{MESI_IT[r['m'] - 1]}" for r in rows],
                full=[f"{MESI_IT_FULL[r['m']]} {r['y']}" for r in rows],
                nec=[r2(r['nec']) for r in rows], ext=[r2(r['ext']) for r in rows],
                sav=[r2(r['sav']) for r in rows], inc=[r2(r['inc']) for r in rows], selected=selected)


# ── Pannello: Categorie rispetto al riferimento ──────────────────────────────

def _cat_sums(conn, start, end):
    ss, se = _span(start, end)
    return {r[0].lower(): r[1] for r in q(conn, """
        SELECT c.category, SUM(e.euro) FROM expenses e
        JOIN category c ON e.category=c.category COLLATE NOCASE AND c.user_id=e.user_id
        WHERE e.user_id=current_uid() AND e.date BETWEEN ? AND ? GROUP BY c.category""", (ss, se))}


TOP_CATEGORIES = 10


def _panel_categorie(conn, p):
    """Le 10 categorie con la spesa più alta nel periodo, dalla più alta, con una tacca di riferimento:
    Mese = media dei 12 mesi precedenti; Anno = lo stesso periodo dell'anno prima."""
    cur = _cat_sums(conn, p['start'], p['end'])
    if p['vista'] == 'mese':
        w_first, w_n = _ref_window(p)
        if w_n:
            y0, m0 = _ym_from_index(w_first)
            y1, m1 = _ym_from_index(w_first + w_n - 1)
            ref = {k: v / w_n for k, v in _cat_sums(conn, date(y0, m0, 1), _month_end(y1, m1)).items()}
        else:
            ref = {}
        ref_label = f"Media degli ultimi {w_n} mesi" if w_n else ''
    else:
        ref = _cat_sums(conn, date(p['year'] - 1, 1, 1), _same_day_prev_year(p['ref']))
        ref_label = f"{p['year'] - 1}, stesso periodo" if ref else ''
    rows = [(name, ctype, cur.get(name.lower(), 0), ref.get(name.lower())) for name, ctype in categories(conn)]
    rows = sorted((r for r in rows if r[2] > 0), key=lambda r: -r[2])[:TOP_CATEGORIES]
    scale = max([r[2] for r in rows] + [r[3] or 0 for r in rows] + [1])
    return dict(ref_label=ref_label, rows=[
        dict(name=name, amount=_eur(v), w=round(v / scale * 100, 2),
             ref=round(r / scale * 100, 2) if r else None, ref_value=_eur(r) if r else '',
             color='var(--data-essential)' if ctype == 'essential' else 'var(--data-extra)')
        for name, ctype, v, r in rows])


# ── Pannello: Cumulata ───────────────────────────────────────────────────────

CUM_VIEWS = ('tot', 'ess', 'ext', 'sav')  # totale, necessità, extra, risparmio


def _daily(conn, start, end, key):
    """{chiave(data): {vista: importo}} con chiave = funzione della data ('YYYY-MM-DD')."""
    ss, se = _span(start, end)
    out = defaultdict(lambda: defaultdict(float))
    for d, e, t in q(conn, """
            SELECT e.date, e.euro, COALESCE(c.type, '') FROM expenses e
            LEFT JOIN category c ON e.category=c.category COLLATE NOCASE AND c.user_id=e.user_id
            WHERE e.user_id=current_uid() AND e.date BETWEEN ? AND ?""", (ss, se)):
        k = key(d)
        out[k]['tot'] += e
        if t == 'essential':
            out[k]['ess'] += e
        elif t == 'extra':
            out[k]['ext'] += e
        out[k]['sav'] -= e
    for d, e in q(conn, "SELECT date, euro FROM incomes WHERE user_id=current_uid() AND date BETWEEN ? AND ?", (ss, se)):
        out[key(d)]['sav'] += e
    return out


def _panel_cumulata(conn, p):
    if p['vista'] == 'mese':
        return _cumulata_mese(conn, p)
    return _cumulata_anno(conn, p)


def _cumulata_mese(conn, p):
    """Giorno per giorno del mese scelto, contro il mese medio dei 12 precedenti (stesso giorno del mese)."""
    n_days = p['end'].day
    upto = p['ref'].day
    w_first, w_n = _ref_window(p)
    y0, m0 = _ym_from_index(w_first)
    data = _daily(conn, date(y0, m0, 1), p['end'], key=lambda d: (d[:7], int(d[8:10])))
    by_month = defaultdict(dict)
    for (ym, day), vals in data.items():
        by_month[ym][day] = vals
    sel = f"{p['year']}-{p['month']:02d}"
    views = {}
    for v in CUM_VIEWS:
        cum, cur = 0, []
        for day in range(1, upto + 1):
            cum += by_month[sel].get(day, {}).get(v, 0)
            cur.append(round(cum, 2))
        avg = None
        if w_n:
            sums = [0.0] * n_days
            for i in range(w_first, w_first + w_n):
                yy, mm = _ym_from_index(i)
                ym, c = f"{yy}-{mm:02d}", 0
                for day in range(1, n_days + 1):
                    c += by_month[ym].get(day, {}).get(v, 0)
                    sums[day - 1] += c
            avg = [round(s / w_n, 2) for s in sums]
        views[v] = dict(cur=cur, avg=avg)
    return dict(mode='mese', days=n_days, label=MESI_IT_FULL[p['month']],
                avg_label=f"Mese medio (ultimi {w_n})" if w_n else '', views=views)


def _cumulata_anno(conn, p):
    """L'anno scelto contro il precedente, con la retta del budget (importi annui di Impostazioni)."""
    y = p['year']
    data = _daily(conn, date(y - 1, 1, 1), date(y, 12, 31),
                  key=lambda d: (int(d[:4]), datetime.strptime(d, '%Y-%m-%d').timetuple().tm_yday))
    ess = budget_for(conn, y, 'essential')
    ext = budget_for(conn, y, 'extra')
    sav = budget_for(conn, y, 'savings')
    targets = {'tot': ess + ext, 'ess': ess, 'ext': ext, 'sav': sav}
    views = {}
    for v in CUM_VIEWS:
        series = []
        for yr in (y - 1, y):
            days = sorted(dd for (yy, dd) in data if yy == yr)
            cumul, xs, vals = 0, [], []
            for dd in days:
                cumul += data[(yr, dd)][v]
                xs.append(dd); vals.append(round(cumul, 2))
            series.append({'year': str(yr), 'x': xs, 'y': vals})
        views[v] = {'series': series, 'target': round(targets[v], 2)}
    return dict(mode='anno', year=y, views=views)


# ── Pagina ───────────────────────────────────────────────────────────────────

@dashboard_bp.route('/')
def index():
    today = datetime.today()
    with finance_db() as conn:
        p = _period(conn, request.args, today)
        panels = dict(
            bilancio=_panel_bilancio(conn, p),
            sunburst=_panel_sunburst(conn, p['start'], p['end']),
            patrimonio=_panel_patrimonio(conn, p),
            mesi=_panel_mesi(conn, p),
            categorie=_panel_categorie(conn, p),
            cumulata=_panel_cumulata(conn, p),
        )
    now = f"{today.year}-{today.month:02d}"
    return render_template('dashboard.html', p=p, now_month=now, now_year=str(today.year), **panels)
