"""Funzioni di utilità condivise tra i blueprint."""
import json
import calendar
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
