from flask import Blueprint, render_template
import json, sys, os
from datetime import datetime
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from db import finance_db
from helpers import q

home_bp = Blueprint('home', __name__)


@home_bp.route('/')
def index():
    today = datetime.today()
    ym    = today.strftime('%Y-%m')
    y     = str(today.year)

    with finance_db() as conn:
        tot_ent = q(conn,
            "SELECT COALESCE(SUM(euro),0) FROM incomes WHERE user_id=1 AND strftime('%Y-%m',date)=?",
            (ym,))[0][0]
        tot_spe = q(conn,
            "SELECT COALESCE(SUM(euro),0) FROM expenses WHERE user_id=1 AND strftime('%Y-%m',date)=?",
            (ym,))[0][0]
        risparmio_mese = tot_ent - tot_spe

        tot_spe_anno = q(conn,
            "SELECT COALESCE(SUM(euro),0) FROM expenses WHERE user_id=1 AND strftime('%Y',date)=?",
            (y,))[0][0]

        spark_rows = q(conn, """
            SELECT strftime('%Y-%m', date) ym, SUM(euro)
            FROM expenses WHERE user_id=1
            GROUP BY ym ORDER BY ym DESC LIMIT 6
        """)
        spark_labels = [r[0] for r in reversed(spark_rows)]
        spark_values = [round(r[1], 2) for r in reversed(spark_rows)]

        top_cats = q(conn, """
            SELECT category, SUM(euro) s FROM expenses
            WHERE user_id=1 AND strftime('%Y',date)=?
            GROUP BY category ORDER BY s DESC LIMIT 5
        """, (y,))

        recent_exp = q(conn, """
            SELECT date, category, description, euro
            FROM expenses WHERE user_id=1
            ORDER BY date DESC, rowid DESC LIMIT 8
        """)

        recent_inc = q(conn, """
            SELECT date, description, euro
            FROM incomes WHERE user_id=1
            ORDER BY date DESC, rowid DESC LIMIT 4
        """)

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
