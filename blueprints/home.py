from flask import Blueprint, render_template
import sqlite3, sys, os, json
from datetime import datetime
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from db import get_finance_conn

home_bp = Blueprint('home', __name__)

@home_bp.route('/')
def index():
    conn  = get_finance_conn()
    today = datetime.today()
    ym    = today.strftime('%Y-%m')
    y     = str(today.year)

    # KPI mese corrente
    tot_ent = conn.execute(
        "SELECT COALESCE(SUM(euro),0) FROM incomes WHERE user_id=1 AND strftime('%Y-%m',date)=?", (ym,)
    ).fetchone()[0]
    tot_spe = conn.execute(
        "SELECT COALESCE(SUM(euro),0) FROM expenses WHERE user_id=1 AND strftime('%Y-%m',date)=?", (ym,)
    ).fetchone()[0]
    risparmio_mese = tot_ent - tot_spe

    # KPI anno corrente
    tot_spe_anno = conn.execute(
        "SELECT COALESCE(SUM(euro),0) FROM expenses WHERE user_id=1 AND strftime('%Y',date)=?", (y,)
    ).fetchone()[0]

    # Ultimi 6 mesi per sparkline
    spark_rows = conn.execute("""
        SELECT strftime('%Y-%m', date) ym, SUM(euro)
        FROM expenses WHERE user_id=1
        GROUP BY ym ORDER BY ym DESC LIMIT 6
    """).fetchall()
    spark_labels = [r[0] for r in reversed(spark_rows)]
    spark_values = [round(r[1], 2) for r in reversed(spark_rows)]

    # Top 5 categorie dell'anno
    top_cats = conn.execute("""
        SELECT category, SUM(euro) s FROM expenses
        WHERE user_id=1 AND strftime('%Y',date)=?
        GROUP BY category ORDER BY s DESC LIMIT 5
    """, (y,)).fetchall()

    # Ultime 8 spese
    recent_exp = conn.execute("""
        SELECT date, category, description, euro
        FROM expenses WHERE user_id=1
        ORDER BY date DESC, rowid DESC LIMIT 8
    """).fetchall()

    # Ultime 4 entrate
    recent_inc = conn.execute("""
        SELECT date, description, euro
        FROM incomes WHERE user_id=1
        ORDER BY date DESC, rowid DESC LIMIT 4
    """).fetchall()

    conn.close()

    max_cat = top_cats[0][1] if top_cats else 1

    return render_template('home.html',
        tot_ent=tot_ent, tot_spe=tot_spe,
        risparmio_mese=risparmio_mese,
        tot_spe_anno=tot_spe_anno,
        mese_corrente=today.strftime('%B %Y'),
        anno_corrente=y,
        spark_labels=json.dumps(spark_labels),
        spark_values=json.dumps(spark_values),
        top_cats=top_cats, max_cat=max_cat,
        recent_exp=recent_exp,
        recent_inc=recent_inc,
    )
