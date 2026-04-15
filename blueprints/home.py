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
        # --- mese corrente ---
        tot_ent = q(conn,
            "SELECT COALESCE(SUM(euro),0) FROM incomes WHERE user_id=1 AND strftime('%Y-%m',date)=?",
            (ym,))[0][0]
        tot_spe = q(conn,
            "SELECT COALESCE(SUM(euro),0) FROM expenses WHERE user_id=1 AND strftime('%Y-%m',date)=?",
            (ym,))[0][0]
        risparmio_mese = tot_ent - tot_spe

        # --- grafico entrate/spese ultimi 6 mesi ---
        spe_rows = q(conn, """
            SELECT strftime('%Y-%m', date) ym, SUM(euro)
            FROM expenses WHERE user_id=1
            GROUP BY ym ORDER BY ym DESC LIMIT 6
        """)
        ent_rows = q(conn, """
            SELECT strftime('%Y-%m', date) ym, SUM(euro)
            FROM incomes WHERE user_id=1
            GROUP BY ym ORDER BY ym DESC LIMIT 6
        """)

        # align on same months
        spe_map = {r[0]: round(r[1], 2) for r in spe_rows}
        ent_map = {r[0]: round(r[1], 2) for r in ent_rows}
        months  = sorted(set(spe_map) | set(ent_map))[-6:]
        spark_labels  = months
        spark_spese   = [spe_map.get(m, 0) for m in months]
        spark_entrate = [ent_map.get(m, 0) for m in months]

        # --- patrimonio ---
        pat_rows = q(conn,
            "SELECT bcc,bbva,directa,deposito,obblig,etf_etc,tfr,fon_te FROM patrimonio ORDER BY anno DESC, mese DESC LIMIT 2")

        pat_now  = None
        pat_prev = None
        donut_data = None
        if pat_rows:
            def _totale(r):
                return r[0]+r[1]+r[2]+r[3]+r[4]+r[5]   # liquidita+deposito+obblig+etf_etc

            pat_now  = pat_rows[0]
            pat_totale = _totale(pat_now)
            pat_delta  = pat_totale - _totale(pat_rows[1]) if len(pat_rows) > 1 else None
            etf_val    = pat_now[5]   # etf_etc

            liquidita  = pat_now[0]+pat_now[1]+pat_now[2]
            emergenza  = pat_now[3]
            breve      = pat_now[4]
            lungo      = pat_now[5]
            previdenza = pat_now[6]+pat_now[7]
            donut_data = json.dumps({
                'labels': ['Liquidità', 'Fondo emergenza', 'Breve termine', 'Lungo termine', 'Previdenza'],
                'values': [round(liquidita,2), round(emergenza,2), round(breve,2), round(lungo,2), round(previdenza,2)],
            })
        else:
            pat_totale = pat_delta = etf_val = None

    return render_template('home.html',
        tot_ent=tot_ent, tot_spe=tot_spe,
        risparmio_mese=risparmio_mese,
        mese_corrente=today.strftime('%B %Y'),
        anno_corrente=y,
        spark_labels=json.dumps(spark_labels),
        spark_spese=json.dumps(spark_spese),
        spark_entrate=json.dumps(spark_entrate),
        pat_totale=pat_totale, pat_delta=pat_delta,
        etf_val=etf_val,
        donut_data=donut_data or 'null',
    )
