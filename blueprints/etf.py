from flask import Blueprint, render_template, request, flash, redirect, url_for, Response
import json, sys, os
from datetime import datetime
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from db import finance_db

etf_bp = Blueprint('etf', __name__)

PERIOD_MAP = {
    '1m': '1mo', '3m': '3mo', '6m': '6mo',
    '12m': '1y', 'ytd': 'ytd', 'max': 'max',
}

PREDEFINED_INDICES = [
    {'ticker': 'VWCE.MI',  'name': 'VWCE – All-World'},
    {'ticker': 'IUSA.MI',  'name': 'IUSA – S&P 500'},
    {'ticker': 'SGLD.MI',  'name': 'SGLD – Oro'},
    {'ticker': 'AGGH.MI',  'name': 'AGGH – Bond Globali'},
    {'ticker': 'IWDA.AS',  'name': 'IWDA – MSCI World'},
    {'ticker': 'BTC-EUR',  'name': 'Bitcoin'},
]

# Indices pre-checked by default (in addition to portfolio tickers)
DEFAULT_INDICES = {'VWCE.MI', 'SGLD.MI', 'BTC-EUR'}


def get_transactions(ticker_filter=''):
    with finance_db() as conn:
        rows = conn.execute(
            "SELECT id, date, ticker, quantity, price FROM transactions ORDER BY date DESC"
        ).fetchall()
    txns = [dict(id=r[0], date=r[1], ticker=r[2], quantity=r[3], price=r[4]) for r in rows]
    if ticker_filter:
        txns = [t for t in txns if ticker_filter.upper() in t['ticker'].upper()]
    return txns


def _dl_close(tickers, yf_period):
    """Download adjusted closing prices. Returns DataFrame or None.
    yfinance 1.x always returns 2-level MultiIndex; raw['Close'] is always a DataFrame."""
    try:
        import yfinance as yf
        import pandas as pd
        if isinstance(tickers, str):
            tickers = [tickers]
        raw = yf.download(tickers, period=yf_period, auto_adjust=True, progress=False)
        if raw.empty:
            return None
        close = raw['Close']  # DataFrame in yf 1.x regardless of ticker count
        close = close.ffill()
        return close
    except Exception as e:
        print(f"[etf] _dl_close error: {e}", file=sys.stderr)
        return None


def get_current_price(ticker):
    """Fetch latest closing price, looking back up to 5 days (handles weekends/holidays)."""
    try:
        import yfinance as yf
        data = yf.Ticker(ticker).history(period='5d')
        if not data.empty:
            return float(data['Close'].iloc[-1])
    except Exception:
        pass
    return None


def _portfolio_history(period='1y'):
    """Returns {'dates': [...], 'series': [{'ticker': tk, 'values': [...]}]} or None.
    Values are portfolio value (€) per ticker per date, for a stacked area chart."""
    from bisect import bisect_right
    import pandas as pd

    with finance_db() as conn:
        rows = conn.execute(
            "SELECT date, ticker, quantity FROM transactions ORDER BY date"
        ).fetchall()

    if not rows:
        return None

    tickers = list(dict.fromkeys(r[1] for r in rows))
    yf_period = PERIOD_MAP.get(period, '1y')

    prices = _dl_close(tickers, yf_period)
    if prices is None or prices.empty:
        return None

    # Build per-ticker cumulative qty lists (already sorted by date)
    tk_dates_list = {tk: [] for tk in tickers}
    tk_qtys_list  = {tk: [] for tk in tickers}
    running = {tk: 0.0 for tk in tickers}
    for date_str, ticker, qty in rows:
        running[ticker] += qty
        tk_dates_list[ticker].append(date_str)
        tk_qtys_list[ticker].append(running[ticker])

    # Filter price history to dates >= first transaction
    first_date = rows[0][0]
    price_dates = [d.strftime('%Y-%m-%d') for d in prices.index]
    filtered = [(i, d) for i, d in enumerate(price_dates) if d >= first_date]
    if not filtered:
        return None

    filtered_idx   = [x[0] for x in filtered]
    filtered_dates = [x[1] for x in filtered]

    series = []
    for tk in tickers:
        if tk not in prices.columns:
            continue
        d_list = tk_dates_list[tk]
        q_list = tk_qtys_list[tk]
        values = []
        for i, d in zip(filtered_idx, filtered_dates):
            idx = bisect_right(d_list, d) - 1
            qty = q_list[idx] if idx >= 0 else 0.0
            pv  = prices[tk].iloc[i]
            values.append(round(qty * float(pv), 2) if pd.notna(pv) else 0.0)
        series.append({'ticker': tk, 'values': values})

    return {'dates': filtered_dates, 'series': series}


def _index_history(tickers, period='1y'):
    """Returns {'dates': [...], 'series': [{'ticker': tk, 'values': [...]}]}
    with % change from period start per ticker, or None."""
    import pandas as pd

    yf_period = PERIOD_MAP.get(period, '1y')
    prices = _dl_close(tickers, yf_period)
    if prices is None or prices.empty:
        return None

    dates = [d.strftime('%Y-%m-%d') for d in prices.index]
    series = []
    for tk in tickers:
        if tk not in prices.columns:
            continue
        col = prices[tk]
        valid = col.dropna()
        if valid.empty:
            continue
        base = float(valid.iloc[0])
        pct_vals = []
        for v in col:
            if pd.isna(v):
                pct_vals.append(None)
            else:
                pct_vals.append(round((float(v) / base - 1) * 100, 2))
        series.append({'ticker': tk, 'values': pct_vals})

    return {'dates': dates, 'series': series}


@etf_bp.route('/etf')
def index():
    ticker_filter = request.args.get('ticker_filter', '')
    txns     = get_transactions(ticker_filter)
    all_txns = get_transactions()
    tickers  = list(dict.fromkeys(t['ticker'] for t in all_txns))

    summary = []
    for tk in tickers:
        tk_txns   = [t for t in all_txns if t['ticker'] == tk]
        tot_qty   = sum(t['quantity'] for t in tk_txns)
        tot_cost  = sum(t['quantity'] * t['price'] for t in tk_txns)
        avg_price = tot_cost / tot_qty if tot_qty else 0
        cur_price = get_current_price(tk)

        if cur_price:
            valore = tot_qty * cur_price
            pm     = valore - tot_cost
            pm_pct = pm / tot_cost * 100 if tot_cost else 0
        else:
            valore = pm = pm_pct = None

        summary.append({
            'ticker':    tk,
            'quantity':  round(tot_qty, 4),
            'avg_price': round(avg_price, 2),
            'cur_price': round(cur_price, 2) if cur_price else None,
            'valore':    round(valore, 2) if valore else None,
            'costo':     round(tot_cost, 2),
            'pm':        round(pm, 2) if pm is not None else None,
            'pm_pct':    round(pm_pct, 2) if pm_pct is not None else None,
        })

    valid        = [s for s in summary if s['valore'] is not None]
    tot_investito = sum(s['costo']  for s in summary)
    tot_val      = sum(s['valore']  for s in valid)
    tot_pm       = tot_val - sum(s['costo'] for s in valid)
    tot_pct      = tot_pm / sum(s['costo'] for s in valid) * 100 if valid else 0

    pie_data = json.dumps({
        'labels': [s['ticker'] for s in valid],
        'values': [s['valore'] for s in valid],
    }) if valid else 'null'

    return render_template('etf.html',
        summary=summary, txns=txns,
        tot_investito=tot_investito, tot_val=tot_val,
        tot_pm=tot_pm, tot_pct=tot_pct,
        ticker_filter=ticker_filter,
        pie_data=pie_data,
        portfolio_tickers=tickers,
        predefined_indices=PREDEFINED_INDICES,
        default_indices=list(DEFAULT_INDICES),
    )


@etf_bp.route('/etf/api/portfolio')
def api_portfolio():
    period = request.args.get('period', '1y')
    data = _portfolio_history(period)
    return Response(json.dumps(data or {}), mimetype='application/json')


@etf_bp.route('/etf/api/indices')
def api_indices():
    period = request.args.get('period', '1y')
    tickers_str = request.args.get('tickers', '')
    tickers = [t.strip() for t in tickers_str.split(',') if t.strip()]
    if not tickers:
        return Response(json.dumps({}), mimetype='application/json')
    data = _index_history(tickers, period)
    return Response(json.dumps(data or {}), mimetype='application/json')


@etf_bp.route('/etf/add', methods=['POST'])
def add():
    date_val = request.form.get('date')
    ticker   = request.form.get('ticker', '').upper().strip()
    try:
        qty   = float(request.form.get('quantity', '0'))
        price = float(request.form.get('price', '0'))
    except ValueError:
        flash('Dati non validi.', 'error')
        return redirect(url_for('etf.index'))

    if not ticker or qty <= 0 or price <= 0:
        flash('Compila tutti i campi correttamente.', 'error')
        return redirect(url_for('etf.index'))

    with finance_db() as conn:
        conn.execute(
            "INSERT INTO transactions (date, ticker, quantity, price) VALUES (?,?,?,?)",
            (date_val, ticker, qty, price))
        conn.commit()
    flash('Acquisto registrato!', 'success')
    return redirect(url_for('etf.index'))


@etf_bp.route('/etf/<int:tid>/delete', methods=['POST'])
def delete(tid):
    with finance_db() as conn:
        conn.execute("DELETE FROM transactions WHERE id=?", (tid,))
        conn.commit()
    flash('Transazione eliminata.', 'success')
    return redirect(url_for('etf.index'))


@etf_bp.route('/etf/<int:tid>/edit', methods=['POST'])
def edit(tid):
    with finance_db() as conn:
        conn.execute(
            "UPDATE transactions SET date=?, ticker=?, quantity=?, price=? WHERE id=?",
            (request.form['date'], request.form['ticker'].upper().strip(),
             float(request.form['quantity']), float(request.form['price']), tid))
        conn.commit()
    flash('Transazione aggiornata.', 'success')
    return redirect(url_for('etf.index'))
