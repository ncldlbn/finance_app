"""Prova di fumo: l'app regge pagine, endpoint e input sbagliati?

    python scripts/smoke.py

Crea un database di esempio temporaneo (mai quello vero), avvia l'app in modalità locale e controlla che:
  1. ogni pagina e ogni endpoint JSON risponda senza errori del server (5xx), con dati e a database vuoto;
  2. input malformati (date inesistenti, importi infiniti, parametri non numerici, id inesistenti…) NON
     provochino errori 500 e NON sporchino il database;
  3. le migrazioni portino un database vuoto all'ultima versione.
Esce con codice 1 se qualcosa non va (è quello che esegue la CI). Non sostituisce una suite di test dei
calcoli: controlla solo che niente si rompa.
"""
import os
import sqlite3
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'scripts'))

failures = []


def check(cond, msg):
    if not cond:
        failures.append(msg)
        print('  FALLITO:', msg)


def make_app(db_path):
    os.environ.update(FINANCE_DB=db_path, FINANCE_LOCAL='1', LOG_DIR=os.path.join(os.path.dirname(db_path), 'logs'))
    for mod in [m for m in sys.modules if m in ('app', 'db', 'config', 'migrations') or m.startswith('blueprints')]:
        del sys.modules[mod]                       # ricarica con il nuovo FINANCE_DB
    from app import create_app
    app = create_app()
    app.config['TESTING'] = False                  # le eccezioni devono passare dai gestori d'errore (500), non propagarsi
    return app


PAGES = ['/', '/input', '/input?tab=entrate', '/input?tab=patrimonio', '/input?tab=ricorrenti', '/elenco', '/elenco?tab=entrate',
         '/monitor', '/grafici', '/patrimonio', '/previste', '/previste?n=12', '/impostazioni', '/elenco/export.csv?tab=spese',
         '/elenco/export.csv?tab=entrate']
JSON_VIEWS = ['flusso', 'composizione', 'andamento']
PERIODS = ['ytd', '5y', 'all', '2025']

MALFORMED_GET = ['/elenco?page_s=abc', '/elenco?page_s=-5', '/elenco?page_s=99999999', '/elenco?anno=abc&mese=zz', '/patrimonio?page=abc',
                 '/previste?start=2026-13', '/previste?n=99', '/impostazioni?anno=abc', '/grafici/dati/andamento?periodo=xxx',
                 '/grafici/cumulata.json?anno=1800', '/grafici/cumulata.json?anno=abc', "/grafici/cumulata.json?anno=2026&cat=' OR 1=1",
                 '/elenco/export.csv?tab=entrate&anno_e=abc', '/non-esiste', '/grafici/dati/nonesiste']
MALFORMED_POST = [
    ('/input', {'action': 'add_expense', 'date': '', 'euro': '1', 'category': ''}),
    ('/input', {'action': 'add_expense', 'date': '2026-13-45', 'euro': '1', 'category': 'Cibo'}),
    ('/input', {'action': 'add_expense', 'date': '2026-01-01', 'euro': '1e999', 'category': 'Cibo'}),
    ('/input', {'action': 'add_expense', 'date': '2026-01-01', 'euro': 'nan', 'category': 'Cibo'}),
    ('/input', {'action': 'add_expense', 'date': '2026-01-01', 'euro': '5', 'category': 'NonEsiste'}),
    ('/input', {'action': 'add_income', 'date': 'oggi', 'euro': 'nan'}),
    ('/input', {'action': 'add_patrimonio', 'anno': 'abc', 'mese': '13'}),
    ('/input', {'action': 'add_patrimonio', 'anno': '2026', 'mese': '13'}),
    ('/input', {'action': 'edit_recurring', 'id': 'abc'}),
    ('/input', {'action': 'delete_recurring', 'id': '99999'}),
    ('/input', {'action': 'toggle_recurring', 'id': '1', 'active': 'x'}),
    ('/input', {'action': 'add_recurring', 'day_of_month': 'abc', 'euro': '1'}),
    ('/input', {'action': 'azione-sconosciuta'}),
    ('/impostazioni/budget', {'year': 'abc', 'essential_value': 'x', 'extra_value': '-5', 'savings_value': '1e999'}),
    ('/impostazioni/add_category', {'name': '', 'type': 'zzz'}),
    ('/previste/add', {'month': '2026-13', 'euro': 'abc', 'description': 'x'}),
    ('/previste/99999/convert', {}),
    ('/elenco/expense/99999/edit', {'date': 'x', 'euro': 'abc', 'category': 'x'}),
    ('/elenco/expense/1/edit', {'date': '2026-01-01', 'euro': 'abc', 'category': 'Cibo'}),
    ('/patrimonio/99999/edit', {'bcc': 'abc'}),
    ('/patrimonio/add', {'anno': 'abc', 'mese': 'abc'}),
]


def main():
    from make_demo_db import main as make_demo
    tmp = tempfile.mkdtemp()
    demo = os.path.join(tmp, 'demo.db')
    make_demo(demo)

    print('1. Pagine ed endpoint con dati')
    c = make_app(demo).test_client()
    for u in PAGES:
        check(c.get(u).status_code < 500, f'GET {u}')
    for v in JSON_VIEWS:
        for p in PERIODS:
            check(c.get(f'/grafici/dati/{v}?periodo={p}').status_code == 200, f'GET /grafici/dati/{v}?periodo={p}')
    for v in ('tot', 'ess', 'ext', 'sav'):
        check(c.get(f'/grafici/cumulata.json?anno=2025&vista={v}&conf=2024').status_code == 200, f'cumulata {v}')

    print('2. Input malformati')
    before = sqlite3.connect(demo).execute('SELECT (SELECT COUNT(*) FROM expenses), (SELECT COUNT(*) FROM incomes), '
                                           '(SELECT COUNT(*) FROM patrimonio)').fetchone()
    for u in MALFORMED_GET:
        check(c.get(u).status_code < 500, f'GET {u}')
    for u, data in MALFORMED_POST:
        r = c.post(u, data=data)
        check(r.status_code < 500, f'POST {u} {data}')
    after = sqlite3.connect(demo).execute('SELECT (SELECT COUNT(*) FROM expenses), (SELECT COUNT(*) FROM incomes), '
                                          '(SELECT COUNT(*) FROM patrimonio)').fetchone()
    check(before == after, f'gli input non validi hanno modificato il database: {before} -> {after}')
    bad = sqlite3.connect(demo).execute("SELECT COUNT(*) FROM expenses WHERE euro > 1e9 OR date NOT GLOB '[0-9][0-9][0-9][0-9]-[01][0-9]-[0-3][0-9]'").fetchone()[0]
    check(bad == 0, f'{bad} spese con data o importo assurdi nel database')

    print('3. Una spesa valida viene inserita (e il tipo segue la categoria)')
    r = c.post('/input', data={'action': 'add_expense', 'date': '2026-02-03', 'euro': '12,50', 'category': 'cibo', 'tipo': 'extra', 'description': 'prova'})
    row = sqlite3.connect(demo).execute("SELECT euro, category, type FROM expenses WHERE description='prova'").fetchone()
    check(r.status_code == 302 and row == (12.5, 'Cibo', 'essential'), f'inserimento valido: {row}')

    print('4. Database vuoto e migrazioni')
    empty = os.path.join(tmp, 'empty.db')
    c2 = make_app(empty).test_client()
    for u in PAGES + ['/grafici/dati/flusso?periodo=all', '/grafici/dati/andamento?periodo=ytd']:
        check(c2.get(u).status_code < 500, f'GET {u} (database vuoto)')
    import migrations
    check(sqlite3.connect(empty).execute('PRAGMA user_version').fetchone()[0] == migrations.LATEST, 'migrazioni non arrivate all\'ultima versione')

    print('\nTutto a posto.' if not failures else f'\n{len(failures)} problemi.')
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
