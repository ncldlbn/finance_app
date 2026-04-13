from flask import Blueprint, render_template, request, flash, redirect, url_for
import json, sys, os
from datetime import datetime
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from db import get_portfolio_conn

etf_bp = Blueprint('etf', __name__)

def get_transactions(ticker_filter=''):
    conn = get_portfolio_conn()
    rows = conn.execute("SELECT id, date, ticker, quantity, price FROM transactions ORDER BY date DESC").fetchall()
    conn.close()
    txns = [dict(id=r[0], date=r[1], ticker=r[2], quantity=r[3], price=r[4]) for r in rows]
    if ticker_filter:
        txns = [t for t in txns if ticker_filter.upper() in t['ticker'].upper()]
    return txns

def get_current_price(ticker):
    try:
        import yfinance as yf
        data = yf.Ticker(ticker).history(period='1d')
        if not data.empty:
            return float(data['Close'].iloc[-1])
    except Exception:
        pass
    return None

@etf_bp.route('/etf')
def index():
    ticker_filter = request.args.get('ticker_filter', '')
    txns = get_transactions(ticker_filter)

    # Unique tickers for summary
    all_txns = get_transactions()
    tickers  = list(dict.fromkeys(t['ticker'] for t in all_txns))

    summary = []
    prices  = {}
    for tk in tickers:
        tk_txns = [t for t in all_txns if t['ticker'] == tk]
        tot_qty  = sum(t['quantity'] for t in tk_txns)
        tot_cost = sum(t['quantity'] * t['price'] for t in tk_txns)
        avg_price = tot_cost / tot_qty if tot_qty else 0
        cur_price = get_current_price(tk)
        prices[tk] = cur_price

        if cur_price:
            valore   = tot_qty * cur_price
            pm       = valore - tot_cost
            pm_pct   = pm / tot_cost * 100 if tot_cost else 0
        else:
            valore = pm = pm_pct = None

        summary.append({
            'ticker': tk, 'quantity': round(tot_qty,4),
            'avg_price': round(avg_price,2), 'cur_price': round(cur_price,2) if cur_price else None,
            'valore': round(valore,2) if valore else None,
            'costo': round(tot_cost,2),
            'pm': round(pm,2) if pm is not None else None,
            'pm_pct': round(pm_pct,2) if pm_pct is not None else None,
        })

    # Totals
    valid    = [s for s in summary if s['valore'] is not None]
    tot_cost = sum(s['costo'] for s in valid)
    tot_val  = sum(s['valore'] for s in valid)
    tot_pm   = tot_val - tot_cost
    tot_pct  = tot_pm / tot_cost * 100 if tot_cost else 0

    # Pie chart data
    pie_data = json.dumps({'labels': [s['ticker'] for s in valid],
                           'values': [s['valore'] for s in valid]}) if valid else 'null'

    return render_template('etf.html',
                           summary=summary, txns=txns,
                           tot_cost=tot_cost, tot_val=tot_val,
                           tot_pm=tot_pm, tot_pct=tot_pct,
                           ticker_filter=ticker_filter,
                           pie_data=pie_data)

@etf_bp.route('/etf/add', methods=['POST'])
def add():
    date_val = request.form.get('date')
    ticker   = request.form.get('ticker','').upper().strip()
    try:
        qty   = float(request.form.get('quantity','0'))
        price = float(request.form.get('price','0'))
    except ValueError:
        flash('Dati non validi.', 'error')
        return redirect(url_for('etf.index'))

    if not ticker or qty <= 0 or price <= 0:
        flash('Compila tutti i campi correttamente.', 'error')
        return redirect(url_for('etf.index'))

    conn = get_portfolio_conn()
    conn.execute("INSERT INTO transactions (date, ticker, quantity, price) VALUES (?,?,?,?)",
                 (date_val, ticker, qty, price))
    conn.commit()
    conn.close()
    flash('✅ Acquisto registrato!', 'success')
    return redirect(url_for('etf.index'))

@etf_bp.route('/etf/<int:tid>/delete', methods=['POST'])
def delete(tid):
    conn = get_portfolio_conn()
    conn.execute("DELETE FROM transactions WHERE id=?", (tid,))
    conn.commit()
    conn.close()
    flash('🗑️ Transazione eliminata.', 'success')
    return redirect(url_for('etf.index'))

@etf_bp.route('/etf/<int:tid>/edit', methods=['POST'])
def edit(tid):
    conn = get_portfolio_conn()
    conn.execute("UPDATE transactions SET date=?, ticker=?, quantity=?, price=? WHERE id=?",
                 (request.form['date'], request.form['ticker'].upper().strip(),
                  float(request.form['quantity']), float(request.form['price']), tid))
    conn.commit()
    conn.close()
    flash('✅ Transazione aggiornata.', 'success')
    return redirect(url_for('etf.index'))
