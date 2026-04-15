"""Funzioni di utilità condivise tra i blueprint."""
import json
import calendar
import math
from datetime import datetime, timedelta
from collections import defaultdict


def q(conn, sql, params=()):
    """Esegue una query e ritorna tutte le righe."""
    return conn.execute(sql, params).fetchall()


def build_month_range(start, end):
    """Ritorna lista di stringhe 'YYYY-MM' da start a end (mese incluso)."""
    months = []
    cur_m = start.replace(day=1)
    end_m = end.replace(day=1)
    while cur_m <= end_m:
        months.append(f"{cur_m.year}-{cur_m.month:02d}")
        if cur_m.month == 12:
            cur_m = cur_m.replace(year=cur_m.year + 1, month=1)
        else:
            cur_m = cur_m.replace(month=cur_m.month + 1)
    return months


def build_monthly_maps(conn, year_filter=None):
    """
    Ritorna (inc_map, spe_map) con chiavi 'YYYY-MM' e valori somma euro.
    Se year_filter (stringa anno) è fornito, filtra solo quell'anno.
    """
    if year_filter:
        inc_rows = q(conn,
            "SELECT strftime('%Y',date) y, strftime('%m',date) m, SUM(euro) "
            "FROM incomes WHERE user_id=1 AND strftime('%Y',date)=? GROUP BY y,m ORDER BY y,m",
            (year_filter,))
        spe_rows = q(conn,
            "SELECT strftime('%Y',e.date) y, strftime('%m',e.date) m, SUM(e.euro) "
            "FROM expenses e WHERE e.user_id=1 AND strftime('%Y',e.date)=? GROUP BY y,m ORDER BY y,m",
            (year_filter,))
    else:
        inc_rows = q(conn,
            "SELECT strftime('%Y',date) y, strftime('%m',date) m, SUM(euro) "
            "FROM incomes WHERE user_id=1 GROUP BY y,m ORDER BY y,m")
        spe_rows = q(conn,
            "SELECT strftime('%Y',e.date) y, strftime('%m',e.date) m, SUM(e.euro) "
            "FROM expenses e WHERE e.user_id=1 GROUP BY y,m ORDER BY y,m")
    inc_map = {f"{r[0]}-{r[1]}": r[2] for r in inc_rows}
    spe_map = {f"{r[0]}-{r[1]}": r[2] for r in spe_rows}
    return inc_map, spe_map


def pct(val, base):
    """Percentuale val/base*100, 0 se base è zero."""
    return val / base * 100 if base else 0


def rule_status(p_ess, p_ext, p_sav):
    """Semaforo verde/giallo/rosso secondo regola 50/30/20."""
    if p_ess <= 50 and p_ext <= 30 and p_sav >= 20:
        return 'green'
    if p_ess <= 60 and p_ext <= 40 and p_sav >= 10:
        return 'yellow'
    return 'red'


def build_hist_rows(months, hist_income, hist_ess, hist_ext):
    """
    Costruisce la lista di dict per la tabella storico + riga totale.
    Ritorna (rows, hist_savings, totals) dove:
      - rows: lista di dict (include riga 'Totale' in fondo)
      - hist_savings: lista valori risparmio per mese
      - totals: dict con tot_inc, tot_ess, tot_ext, tot_exp, tot_sav, nm,
                avg_inc, avg_exp, avg_sav
    """
    hist_savings = [hist_income[i] - hist_ess[i] - hist_ext[i] for i in range(len(months))]
    rows = []
    for i, m in enumerate(months):
        inc = hist_income[i]
        ess = hist_ess[i]
        ext = hist_ext[i]
        exp = ess + ext
        sav = hist_savings[i]
        p_ess = pct(ess, inc)
        p_ext = pct(ext, inc)
        p_sav = pct(sav, inc)
        rows.append({
            'label':   m,
            'inc':     inc,
            'exp':     exp,
            'ess':     ess,
            'ext':     ext,
            'sav':     sav,
            'pct_exp': pct(exp, inc),
            'pct_ess': p_ess,
            'pct_ext': p_ext,
            'pct_sav': p_sav,
            'status':  rule_status(p_ess, p_ext, p_sav) if inc > 0 else None,
        })

    tot_inc = sum(hist_income)
    tot_ess = sum(hist_ess)
    tot_ext = sum(hist_ext)
    tot_exp = tot_ess + tot_ext
    tot_sav = sum(hist_savings)
    nm = len(months) or 1
    tp_ess = pct(tot_ess, tot_inc)
    tp_ext = pct(tot_ext, tot_inc)
    tp_sav = pct(tot_sav, tot_inc)
    rows.append({
        'label':    'Totale',
        'inc':      tot_inc,
        'exp':      tot_exp,
        'ess':      tot_ess,
        'ext':      tot_ext,
        'sav':      tot_sav,
        'pct_exp':  pct(tot_exp, tot_inc),
        'pct_ess':  tp_ess,
        'pct_ext':  tp_ext,
        'pct_sav':  tp_sav,
        'status':   rule_status(tp_ess, tp_ext, tp_sav) if tot_inc > 0 else None,
        'is_total': True,
    })

    totals = {
        'tot_inc': tot_inc, 'tot_ess': tot_ess, 'tot_ext': tot_ext,
        'tot_exp': tot_exp, 'tot_sav': tot_sav, 'nm': nm,
        'avg_inc': tot_inc / nm, 'avg_exp': tot_exp / nm, 'avg_sav': tot_sav / nm,
    }
    return rows, hist_savings, totals


def parse_period(period, today):
    """
    Converte una stringa periodo in (start, end) datetime.
    start è None per il periodo 'all' (il caller deve ricavarlo dal DB).
    """
    if period == 'ytd':
        start = datetime(today.year, 1, 1)
    elif period == '6m':
        start = today.replace(day=1)
        for _ in range(6):
            start = (start - timedelta(days=1)).replace(day=1)
    elif period == '12m':
        m = today.month - 11
        y = today.year
        if m <= 0:
            m += 12
            y -= 1
        start = datetime(y, m, 1)
    elif period == '5y':
        start = datetime(today.year - 4, 1, 1)
    else:
        start = None  # 'all'
    last_day = calendar.monthrange(today.year, today.month)[1]
    end = today.replace(day=last_day)
    return start, end


# ── Budget estimation ─────────────────────────────────────────────────────────

BUDGET_WINDOW = 24   # mesi di storico


def budget_prev_months(n, ref=None):
    """Ultimi n mesi completi (esclude il mese corrente), ordine cronologico."""
    if ref is None:
        ref = datetime.today()
    y, m = ref.year, ref.month - 1
    if m == 0:
        m, y = 12, y - 1
    months = []
    for _ in range(n):
        months.append(f"{y}-{m:02d}")
        m -= 1
        if m == 0:
            m, y = 12, y - 1
    return list(reversed(months))


def _budget_ewma(values, lam):
    if not values:
        return 0.0
    weights = [lam ** (len(values) - 1 - i) for i in range(len(values))]
    return sum(w * v for w, v in zip(weights, values)) / sum(weights)


def _budget_cv(values):
    nz = [v for v in values if v > 0]
    if len(nz) < 2:
        return 0.0
    mean = sum(nz) / len(nz)
    if mean == 0:
        return 0.0
    return math.sqrt(sum((v - mean) ** 2 for v in nz) / len(nz)) / mean


def budget_estimate_category(monthly_values, cat_type):
    """Stima la spesa mensile attesa per una categoria."""
    n_total   = len(monthly_values)
    nonzero   = [v for v in monthly_values if v > 0]
    n_nonzero = len(nonzero)
    cv        = _budget_cv(monthly_values)

    if n_nonzero == 0:
        return dict(estimate=0.0, confidence='low', method='no_data',
                    n_months=n_total, n_nonzero=0, cv=0.0)

    if n_nonzero < 3:
        freq     = n_nonzero / n_total
        estimate = (sum(nonzero) / n_nonzero) * freq
        return dict(estimate=round(estimate, 2), confidence='low', method='scarso',
                    n_months=n_total, n_nonzero=n_nonzero, cv=cv)

    if cat_type == 'extra' or cv >= 0.55:
        freq       = n_nonzero / n_total
        avg_when   = sum(nonzero) / n_nonzero
        estimate   = avg_when * freq
        confidence = 'low' if cv > 0.8 else ('medium' if cv > 0.4 else 'high')
        return dict(estimate=round(estimate, 2), confidence=confidence,
                    method='frequenza', n_months=n_total, n_nonzero=n_nonzero, cv=cv)

    if cv < 0.25:
        lam, confidence, method = 0.92, 'high',   'ewma_stabile'
    else:
        lam, confidence, method = 0.82, 'medium', 'ewma_variabile'

    estimate = _budget_ewma(monthly_values, lam)
    return dict(estimate=round(estimate, 2), confidence=confidence,
                method=method, n_months=n_total, n_nonzero=n_nonzero, cv=cv)


def compute_budget(conn, ref=None):
    """
    Calcola stime di budget per entrate, uscite (per categoria) e risparmio.
    Ritorna un dict pronto per il template.
    """
    months  = budget_prev_months(BUDGET_WINDOW, ref)
    m_start, m_end = months[0], months[-1]

    # Spese per categoria e mese
    exp_rows = q(conn, """
        SELECT strftime('%Y-%m', e.date) ym,
               e.category,
               COALESCE(c.type, 'extra') as type,
               SUM(e.euro) as total
        FROM expenses e
        LEFT JOIN category c ON e.category = c.category
        WHERE e.user_id = 1
          AND strftime('%Y-%m', e.date) >= ?
          AND strftime('%Y-%m', e.date) <= ?
        GROUP BY ym, e.category
        ORDER BY e.category, ym
    """, (m_start, m_end))

    cat_data = defaultdict(lambda: {'type': 'extra', 'monthly': {}})
    for ym, cat, cat_type, total in exp_rows:
        cat_data[cat]['type']        = cat_type
        cat_data[cat]['monthly'][ym] = float(total)

    cats = []
    for cat, data in sorted(cat_data.items()):
        mv  = [data['monthly'].get(m, 0.0) for m in months]
        est = budget_estimate_category(mv, data['type'])
        if est['estimate'] > 0:
            cats.append({'category': cat, 'type': data['type'], **est})
    cats.sort(key=lambda r: (0 if r['type'] == 'essential' else 1, -r['estimate']))

    tot_essential = sum(r['estimate'] for r in cats if r['type'] == 'essential')
    tot_extra     = sum(r['estimate'] for r in cats if r['type'] == 'extra')
    tot_exp       = tot_essential + tot_extra

    # Entrate: EWMA sugli ultimi BUDGET_WINDOW mesi
    inc_rows = q(conn, """
        SELECT strftime('%Y-%m', date) ym, SUM(euro)
        FROM incomes WHERE user_id=1
          AND strftime('%Y-%m', date) >= ? AND strftime('%Y-%m', date) <= ?
        GROUP BY ym
    """, (m_start, m_end))
    inc_map = {r[0]: float(r[1]) for r in inc_rows}
    inc_values = [inc_map.get(m, 0.0) for m in months]
    inc_nonzero = [v for v in inc_values if v > 0]
    if len(inc_nonzero) >= 3:
        est_income = round(_budget_ewma(inc_values, 0.88), 2)
    elif inc_nonzero:
        est_income = round(sum(inc_nonzero) / len(inc_nonzero), 2)
    else:
        est_income = 0.0

    est_savings = round(est_income - tot_exp, 2)
    bil_max     = max((r['estimate'] for r in cats), default=1) or 1

    return dict(
        est_income=est_income,
        est_expense=round(tot_exp, 2),
        est_savings=est_savings,
        est_essential=round(tot_essential, 2),
        est_extra=round(tot_extra, 2),
        budget_cats=cats,
        budget_max=bil_max,
        budget_window=BUDGET_WINDOW,
        budget_period=f"{m_start} / {m_end}",
    )
