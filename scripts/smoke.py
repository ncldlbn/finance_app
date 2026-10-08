"""Prova di fumo: l'app regge pagine, endpoint e input sbagliati?

    python scripts/smoke.py

Crea un database di esempio temporaneo (mai quello vero), avvia l'app in modalità locale e controlla che:
  1. ogni pagina e ogni endpoint JSON risponda senza errori del server (5xx), con dati e a database vuoto;
  2. input malformati (date inesistenti, importi infiniti, parametri non numerici, id inesistenti…) NON
     provochino errori 500 e NON sporchino il database;
  3. le migrazioni portino un database vuoto all'ultima versione;
  4. ISOLAMENTO TRA UTENTI: con due utenti e un account demo, nessuno vede né modifica dati altrui (pagine,
     endpoint JSON, esportazione, modifica/eliminazione per id), l'account demo è in sola lettura, l'accesso è
     obbligatorio, le richieste da altri siti sono rifiutate e il login ha un limite di tentativi.
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


HDR = {'Origin': 'http://localhost'}                  # il client di prova risponde come host "localhost"


def make_users(db):
    """Due utenti normali (anna, bruno) con dati contrassegnati da stringhe uniche, più un account demo."""
    import demo_data
    import migrations
    from werkzeug.security import generate_password_hash
    migrations.migrate(db, log=lambda *_: None)
    conn = sqlite3.connect(db)
    ids = {}
    for name, marker in (('anna', 'AAAA'), ('bruno', 'BBBB'), ('demo', None)):
        cur = conn.execute('INSERT INTO users (username, password_hash, is_demo) VALUES (?,?,?)',
                           (name, generate_password_hash(f'password-di-{name}'), int(name == 'demo')))
        uid = ids[name] = cur.lastrowid
        if name == 'demo':
            demo_data.populate(conn, uid)
            conn.execute('UPDATE users SET data_date=? WHERE id=?', (__import__('datetime').date.today().isoformat(), uid))
            continue
        demo_data.seed_categories(conn, uid)
        conn.execute('INSERT INTO category (user_id, type, category) VALUES (?, "extra", ?)', (uid, f'Cat{marker}'))
        conn.execute('INSERT INTO expenses (date, user_id, euro, description, category, type) VALUES (?,?,?,?,?,?)',
                     ('2026-03-05', uid, 11.11, f'Spesa{marker}', f'Cat{marker}', 'extra'))
        conn.execute('INSERT INTO incomes (date, user_id, euro, description) VALUES (?,?,?,?)', ('2026-03-01', uid, 2222.0, f'Entrata{marker}'))
        conn.execute('INSERT INTO patrimonio (user_id, anno, mese, bcc) VALUES (?,?,?,?)', (uid, 2026, 3, 33333.0 if marker == 'AAAA' else 44444.0))
        conn.execute('INSERT INTO recurring_expenses (user_id, day_of_month, euro, type, category, description) VALUES (?,?,?,?,?,?)',
                     (uid, 7, 9.0, 'extra', f'Cat{marker}', f'Ricorrente{marker}'))
        conn.execute('INSERT INTO planned_expenses (user_id, month, euro, description, category, due_date) VALUES (?,?,?,?,?,?)',
                     (uid, '2026-11', 55.0, f'Prevista{marker}', f'Cat{marker}', ''))
        conn.execute('INSERT INTO budgets (user_id, year, kind, value, period) VALUES (?,?,?,?,?)', (uid, 2026, 'extra', 12345.0 if marker == 'AAAA' else 54321.0, 'annuale'))
    conn.commit()
    conn.close()
    return ids


def login(app, username, password):
    c = app.test_client()
    r = c.post('/login', data={'username': username, 'password': password}, headers=HDR)
    return c, r


def isolation_section():
    print('4. Utenti, accesso e isolamento')
    tmp = tempfile.mkdtemp()
    db = os.path.join(tmp, 'multi.db')
    make_app(db)                                     # crea lo schema (modalità locale, nessun utente)
    ids = make_users(db)
    app = make_app(db)
    anon = app.test_client()

    # 4a. senza accesso non si vede nulla
    for u in PAGES + ['/grafici/dati/flusso?periodo=all', '/grafici/cumulata.json?anno=2026']:
        r = anon.get(u)
        check(r.status_code == 302 and '/login' in r.headers.get('Location', ''), f'senza accesso {u} dovrebbe rimandare al login ({r.status_code})')
    check(anon.post('/input', data={'action': 'add_income', 'date': '2026-01-01', 'euro': '1'}, headers=HDR).status_code == 302, 'POST senza accesso')

    # 4b. login: errori, limite di tentativi, accesso corretto
    c_anna, r = login(app, 'Anna', 'password-di-anna')                    # il nome utente non distingue le maiuscole
    check(r.status_code == 302 and c_anna.get('/').status_code == 200, 'login di anna')
    for _ in range(5):
        login(app, 'bruno', 'sbagliata')
    check(login(app, 'bruno', 'password-di-bruno')[1].status_code == 429, 'dopo 5 errori il login deve rispondere 429')
    with sqlite3.connect(db) as conn:
        conn.execute('DELETE FROM login_attempts')
    c_bruno, r = login(app, 'bruno', 'password-di-bruno')
    check(r.status_code == 302 and c_bruno.get('/').status_code == 200, 'login di bruno')
    check(login(app, 'nessuno', 'x')[1].status_code == 200, 'utente inesistente: errore, non 500')

    # 4c. ognuno vede solo i propri dati
    read_pages = ['/elenco', '/elenco?tab=entrate', '/elenco?desc=Spesa', '/elenco/export.csv?tab=spese', '/elenco/export.csv?tab=entrate',
                  '/patrimonio', '/previste', '/previste?start=2026-11', '/input', '/input?tab=ricorrenti', '/impostazioni?anno=2026',
                  '/monitor', '/', '/grafici/dati/flusso?periodo=all', '/grafici/dati/composizione?periodo=all',
                  '/grafici/dati/andamento?periodo=all', '/grafici/dati/andamento?periodo=2026',
                  '/grafici/cumulata.json?anno=2026&vista=tot', '/grafici/cumulata.json?anno=2026&vista=ext&conf=2025',
                  '/grafici/cumulata.json?anno=2026&cat=CatAAAA']
    for me, other, mk_me, mk_other in ((c_anna, c_bruno, 'AAAA', 'BBBB'), (c_bruno, c_anna, 'BBBB', 'AAAA')):
        for u in read_pages:
            body = me.get(u).get_data(as_text=True)
            check(mk_other not in body, f'«{u}» mostra dati dell\'altro utente ({mk_other})')
    seen = c_anna.get('/elenco?desc=Spesa').get_data(as_text=True)
    check('SpesaAAAA' in seen, "anna non vede la propria spesa (il test non sarebbe significativo)")
    check('33333' in c_anna.get('/patrimonio').get_data(as_text=True) and '44444' not in c_anna.get('/patrimonio').get_data(as_text=True), 'patrimonio di anna')
    for me, mine, theirs, name in ((c_anna, '12345', '54321', 'anna'), (c_bruno, '54321', '12345', 'bruno')):
        page = me.get('/impostazioni?anno=2026').get_data(as_text=True)
        check(mine in page and theirs not in page, f'budget di {name} nelle Impostazioni')
        target = me.get('/grafici/cumulata.json?anno=2026&vista=ext').get_json()['target']
        check(target == float(mine), f'target delle cumulate di {name}: {target} invece di {mine}')

    # 4d. nessuna scrittura sui dati altrui, nemmeno indovinando gli id
    def rows(table, uid):
        with sqlite3.connect(db) as conn:
            return conn.execute(f'SELECT * FROM {table} WHERE user_id=? ORDER BY id', (uid,)).fetchall()
    tables = ['expenses', 'incomes', 'patrimonio', 'recurring_expenses', 'planned_expenses', 'category', 'budgets']

    def snapshot(uid):
        with sqlite3.connect(db) as conn:
            return {t: conn.execute(f'SELECT * FROM {t} WHERE user_id=?', (uid,)).fetchall() for t in tables}
    anna_before = snapshot(ids['anna'])
    with sqlite3.connect(db) as conn:
        a = {t: [r[0] for r in conn.execute(f'SELECT id FROM {t} WHERE user_id=?', (ids['anna'],)) if t != 'budgets'] for t in tables if t != 'budgets'}
    for eid in a['expenses']:
        c_bruno.post(f'/elenco/expense/{eid}/delete', headers=HDR)
        c_bruno.post(f'/elenco/expense/{eid}/edit', data={'date': '2026-01-01', 'euro': '1', 'category': 'Casa'}, headers=HDR)
    for iid in a['incomes']:
        c_bruno.post(f'/elenco/income/{iid}/delete', headers=HDR)
        c_bruno.post(f'/elenco/income/{iid}/edit', data={'date': '2026-01-01', 'euro': '1'}, headers=HDR)
    for pid in a['patrimonio']:
        c_bruno.post(f'/patrimonio/{pid}/delete', headers=HDR)
        c_bruno.post(f'/patrimonio/{pid}/edit', data={'bcc': '1'}, headers=HDR)
    for rid in a['recurring_expenses']:
        c_bruno.post('/input', data={'action': 'delete_recurring', 'id': rid}, headers=HDR)
        c_bruno.post('/input', data={'action': 'toggle_recurring', 'id': rid, 'active': '0'}, headers=HDR)
        c_bruno.post('/input', data={'action': 'edit_recurring', 'id': rid, 'day_of_month': '1', 'euro': '1', 'category': 'Casa'}, headers=HDR)
        c_bruno.post('/input', data={'action': 'confirm_recurring', 'rule_ids': rid}, headers=HDR)
    for pid in a['planned_expenses']:
        c_bruno.post(f'/previste/{pid}/delete', headers=HDR)
        c_bruno.post(f'/previste/{pid}/convert', headers=HDR)
    c_bruno.post('/impostazioni/save', data={f'budget_{cid}': '999' for cid in a['category']}, headers=HDR)
    check(anna_before == snapshot(ids['anna']), 'bruno è riuscito a modificare o eliminare dati di anna')
    # ... e le scritture proprie finiscono solo sul proprio utente
    bruno_exp = len(rows('expenses', ids['bruno']))
    c_bruno.post('/input', data={'action': 'add_expense', 'date': '2026-04-01', 'euro': '3', 'category': 'CatBBBB', 'description': 'nuova'}, headers=HDR)
    check(len(rows('expenses', ids['bruno'])) == bruno_exp + 1 and anna_before == snapshot(ids['anna']), 'una spesa di bruno deve finire solo a bruno')
    c_bruno.post('/impostazioni/budget', data={'year': '2026', 'essential_value': '1', 'extra_value': '7', 'savings_value': '1'}, headers=HDR)
    check(anna_before == snapshot(ids['anna']), 'il budget di bruno ha cambiato quello di anna')
    c_bruno.post('/impostazioni/add_category', data={'name': 'CatBRUNO2', 'type': 'extra'}, headers=HDR)
    check('CatBRUNO2' not in c_anna.get('/input').get_data(as_text=True), 'la categoria di bruno compare ad anna')
    # una spesa di anna non può usare una categoria di bruno (le categorie sono per utente)
    check(anna_before == snapshot(ids['anna']) and c_anna.post('/input', data={'action': 'add_expense', 'date': '2026-04-01', 'euro': '3', 'category': 'CatBBBB'}, headers=HDR).status_code == 302
          and not any(r[5] == 'CatBBBB' for r in rows('expenses', ids['anna'])), "anna ha usato una categoria di bruno")

    # 4e. richieste da altri siti
    before = snapshot(ids['anna'])
    r = c_anna.post('/input', data={'action': 'add_income', 'date': '2026-05-05', 'euro': '77'}, headers={'Origin': 'http://sito-malevolo.example'})
    check(r.status_code == 400 and snapshot(ids['anna']) == before, 'una richiesta con Origin estraneo deve essere rifiutata')

    # 4f. account demo: dati propri, sola lettura
    c_demo, r = login(app, 'demo', 'password-di-demo')
    check(r.status_code == 302, 'login demo')
    body = c_demo.get('/elenco').get_data(as_text=True)
    check('AAAA' not in body and 'BBBB' not in body and 'Affitto' in body, "l'account demo vede dati che non sono i suoi")
    demo_before = snapshot(ids['demo'])
    for u, d in (('/input', {'action': 'add_expense', 'date': '2026-04-01', 'euro': '3', 'category': 'Cibo'}),
                 ('/input', {'action': 'add_income', 'date': '2026-04-01', 'euro': '3'}),
                 ('/impostazioni/budget', {'year': '2026', 'essential_value': '1', 'extra_value': '1', 'savings_value': '1'}),
                 ('/impostazioni/add_category', {'name': 'NuovaDemo', 'type': 'extra'}),
                 ('/previste/add', {'month': '2026-12', 'euro': '5', 'description': 'x'})):
        r = c_demo.post(u, data=d, headers=HDR)
        check(r.status_code == 302, f'demo: POST {u} dovrebbe rimandare con un avviso')
    r = c_demo.post('/input', data={'action': 'add_income', 'date': '2026-04-01', 'euro': '3'}, headers={**HDR, 'X-Requested-With': 'XMLHttpRequest'})
    check(r.status_code == 403, 'demo: una richiesta XHR di scrittura deve dare 403')
    check(snapshot(ids['demo']) == demo_before, "l'account demo ha scritto dati")
    # i dati demo si rinnovano ogni giorno: con una data vecchia vengono rigenerati al login
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE users SET data_date='2000-01-01' WHERE id=?", (ids['demo'],))
        conn.execute('DELETE FROM expenses WHERE user_id=?', (ids['demo'],))
    login(app, 'demo', 'password-di-demo')
    check(len(rows('expenses', ids['demo'])) > 100, 'i dati demo non sono stati rigenerati al login')
    check(snapshot(ids['anna']) == before, "il rinnovo dei dati demo ha toccato altri utenti")

    # 4g. cambiare la password invalida le sessioni di quell'utente
    from werkzeug.security import generate_password_hash
    with sqlite3.connect(db) as conn:
        conn.execute('UPDATE users SET password_hash=? WHERE id=?', (generate_password_hash('nuova-password-1'), ids['bruno']))
    r = c_bruno.get('/elenco')
    check(r.status_code == 302 and '/login' in r.headers['Location'], 'la sessione di bruno doveva decadere dopo il cambio password')


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

    isolation_section()

    print('\nTutto a posto.' if not failures else f'\n{len(failures)} problemi.')
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
