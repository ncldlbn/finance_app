from flask import Blueprint, Response, g, jsonify, render_template, request, flash, redirect, session, url_for
import sys, os, time
from werkzeug.security import check_password_hash, generate_password_hash
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from db import finance_db
from datetime import datetime
import wealth
from helpers import q, all_years, budget_row, BUDGET_KINDS
import importer
from blueprints.auth import fingerprint
from validators import (ValidationError, parse_amount, parse_id, parse_int, parse_text, year_arg,
                        YEAR_MIN, YEAR_MAX)

impostazioni_bp = Blueprint('impostazioni', __name__)

TABS = [('categorie', 'Categorie', 'category'), ('budget', 'Budget', 'flag'), ('patrimonio', 'Patrimonio', 'account_balance'),
        ('dati', 'Dati', 'upload_file'), ('tema', 'Tema', 'palette'), ('account', 'Account', 'manage_accounts')]
TAB_KEYS = [t[0] for t in TABS]
PASSWORD_MIN = 8                       # come scripts/set_password.py


def _tab_arg():
    tab = request.args.get('tab') or request.form.get('tab') or 'categorie'
    return tab if tab in TAB_KEYS else 'categorie'


def _back(tab, **kw):
    return redirect(url_for('impostazioni.index', tab=tab, **kw))


@impostazioni_bp.route('/impostazioni')
def index():
    return _render(_tab_arg())


def _render(tab, report=None):
    """Pagina Impostazioni; `report` è l'esito dell'ultima importazione (se è appena avvenuta)."""
    this_year = datetime.now().year
    anno = year_arg('anno', this_year)
    ctx = dict(tab=tab, tabs=TABS, report=report, formats=importer.FORMATS)
    with finance_db() as conn:
        if tab == 'categorie':
            rows = q(conn, """
                SELECT c.id, c.type, c.category, c.visible,
                       (SELECT COUNT(*) FROM expenses e WHERE e.user_id=c.user_id AND e.category=c.category COLLATE NOCASE),
                       (SELECT COUNT(*) FROM recurring_expenses r WHERE r.user_id=c.user_id AND r.category=c.category COLLATE NOCASE)
                FROM category c WHERE c.user_id=current_uid() ORDER BY c.type, c.position, c.id""")
            cats = [dict(id=r[0], type=r[1], name=r[2], visible=bool(r[3]), n_exp=r[4], n_rec=r[5]) for r in rows]
            ctx.update(essential=[c for c in cats if c['type'] == 'essential'],
                       extra=[c for c in cats if c['type'] == 'extra'], all_cats=cats)
        elif tab == 'budget':
            data_years = [int(y) for y in all_years(conn)]
            # Budget validi per l'anno scelto; `from_year` dice da quale anno vengono se l'anno non ne ha di propri.
            budgets = {}
            for kind in BUDGET_KINDS:
                row = budget_row(conn, anno, kind)
                budgets[kind] = {'value': row[0] if row else 0.0, 'period': row[1] if row else 'annuale',
                                 'from_year': row[2] if row else None}
            explicit = {r[0] for r in q(conn, "SELECT kind FROM budgets WHERE user_id=current_uid() AND year=?", (anno,))}
            years = sorted({this_year + 1, this_year, anno, *data_years}, reverse=True)
            ctx.update(budgets=budgets, budget_year=anno, budget_years=years,
                       inherited=[k for k in BUDGET_KINDS if k not in explicit])
        elif tab == 'patrimonio':
            wcfg = wealth.config(conn)
            ctx.update(wealth_cfg=wcfg, w_hidden=wealth.hidden_with_values(conn, wcfg), presets=wealth.PRESET_LABELS)
    # L'account si gestisce solo con un accesso vero: in modalità locale senza utenti non c'è nessuna password.
    ctx['can_manage_account'] = g.user['username'] != 'locale' and not g.user['is_demo']
    return render_template('impostazioni.html', **ctx)


@impostazioni_bp.route('/impostazioni/budget', methods=['POST'])
def save_budget():
    """Salva i tre budget (necessità, extra, risparmio) per l'anno scelto: importo e periodo
    (mensile o annuale; l'annuale è il mensile x 12). Gli anni successivi senza budget propri
    ereditano questi."""
    anno = parse_int(request.form.get('year'), 'year', 'Anno', YEAR_MIN, YEAR_MAX)
    with finance_db() as conn:
        for kind in BUDGET_KINDS:
            val = parse_amount(request.form.get(f'{kind}_value') or '0', f'{kind}_value', 'Budget', positive=True)
            period = request.form.get(f'{kind}_period', 'annuale')
            if period not in ('mensile', 'annuale'):
                period = 'annuale'
            conn.execute("INSERT INTO budgets (user_id, year, kind, value, period) VALUES (current_uid(),?,?,?,?) "
                         "ON CONFLICT(user_id, year, kind) DO UPDATE SET value=excluded.value, period=excluded.period",
                         (anno, kind, val, period))
        conn.commit()
    flash(f'Budget {anno} salvato.', 'success')
    return _back('budget', anno=anno)


@impostazioni_bp.route('/impostazioni/patrimonio', methods=['POST'])
def save_patrimonio():
    """Nome e visibilità di ogni posto, e quali gruppi contano nel totale. Il pulsante rapido (`preset`)
    imposta solo la regola del totale. I valori già inseriti non si toccano mai."""
    preset = request.form.get('preset')
    with finance_db() as conn:
        if preset in wealth.PRESETS:
            counts = {g['key']: g['key'] in wealth.PRESETS[preset] for g in wealth.GROUPS}
            labels = {c: None for c in wealth.ALL_SLOTS}             # con un pulsante rapido nomi e visibilità restano
        else:
            counts = {g['key']: request.form.get(f"count_{g['key']}") == '1' for g in wealth.GROUPS}
            labels = {c: parse_text(request.form.get(f'label_{c}'), f'label_{c}', 'Nome', max_len=wealth.LABEL_MAX) or wealth.SLOT_DEFAULT_LABEL[c]
                      for c in wealth.ALL_SLOTS}
        for grp, on in counts.items():
            conn.execute('INSERT INTO wealth_group_settings (user_id, grp, counts) VALUES (current_uid(),?,?) '
                         'ON CONFLICT(user_id, grp) DO UPDATE SET counts=excluded.counts', (grp, int(on)))
        if not preset:
            for code, label in labels.items():
                conn.execute('INSERT INTO wealth_slots (user_id, slot, label, visible) VALUES (current_uid(),?,?,?) '
                             'ON CONFLICT(user_id, slot) DO UPDATE SET label=excluded.label, visible=excluded.visible',
                             (code, label, int(request.form.get(f'vis_{code}') == '1')))
        conn.commit()
    flash('Totale impostato su «%s».' % wealth.PRESET_LABELS[preset] if preset in wealth.PRESETS else 'Patrimonio salvato.', 'success')
    return _back('patrimonio')


# ── Categorie ────────────────────────────────────────────────────────────────

@impostazioni_bp.route('/impostazioni/add_category', methods=['POST'])
def add_category():
    name = parse_text(request.form.get('name'), 'name', 'Nome', required=True, max_len=60)
    tipo = request.form.get('type', '')
    if tipo not in ('essential', 'extra'):
        raise ValidationError('Tipo non valido.', 'type')
    with finance_db() as conn:
        # Il nome è unico fra TUTTE le categorie (anche di tipo diverso): le spese le collegano per nome.
        existing = conn.execute("SELECT category FROM category WHERE user_id=current_uid() AND category=? COLLATE NOCASE",
                                (name,)).fetchone()
        if existing:
            flash(f'La categoria "{existing[0]}" esiste già.', 'warning')
        else:
            last = conn.execute("SELECT COALESCE(MAX(position),0) FROM category WHERE user_id=current_uid() AND type=?",
                                (tipo,)).fetchone()[0]
            conn.execute("INSERT INTO category (user_id, type, category, budget, position) VALUES (current_uid(),?,?,0,?)",
                         (tipo, name, last + 1))
            conn.commit()
            flash(f'Categoria "{name}" aggiunta.', 'success')
    return _back('categorie')


@impostazioni_bp.route('/impostazioni/categorie/visibilita', methods=['POST'])
def save_category_visibility():
    """Quali categorie sono una colonna del Monitor. Le nascoste restano ovunque (inserimento, elenco, grafici)
    e i loro importi restano nei totali del Monitor: cambia solo la colonna."""
    with finance_db() as conn:
        for (cid,) in q(conn, "SELECT id FROM category WHERE user_id=current_uid()"):
            conn.execute("UPDATE category SET visible=? WHERE id=? AND user_id=current_uid()",
                         (int(request.form.get(f'vis_{cid}') == '1'), cid))
        conn.commit()
    flash('Visibilità nel Monitor salvata.', 'success')
    return _back('categorie')


THEMES = ('auto', 'light', 'dark')


@impostazioni_bp.route('/impostazioni/tema', methods=['POST'])
def save_theme():
    """Tema dell'interfaccia dell'utente (auto = come il sistema). Risposta JSON: lo chiama la pagina stessa."""
    theme = (request.get_json(silent=True) or {}).get('theme')
    if theme not in THEMES:
        raise ValidationError('Tema non valido.')
    with finance_db(user_id=g.user['id']) as conn:
        conn.execute("UPDATE users SET theme=? WHERE id=?", (theme, g.user['id']))
        conn.commit()
    return jsonify(ok=True)


@impostazioni_bp.route('/impostazioni/categorie/ordine', methods=['POST'])
def save_category_order():
    """Salva l'ordine di visualizzazione delle categorie di un tipo (JSON: {type, ids}). `ids` deve contenere
    ESATTAMENTE le categorie di quel tipo, ciascuna una volta: ordine parziale o id altrui vengono rifiutati."""
    data = request.get_json(silent=True) or {}
    tipo, ids = data.get('type'), data.get('ids')
    if tipo not in ('essential', 'extra') or not isinstance(ids, list) or not all(isinstance(i, int) for i in ids):
        raise ValidationError('Richiesta non valida.')
    with finance_db() as conn:
        mine = {r[0] for r in q(conn, "SELECT id FROM category WHERE user_id=current_uid() AND type=?", (tipo,))}
        if len(ids) != len(set(ids)) or set(ids) != mine:
            raise ValidationError("L'elenco delle categorie non corrisponde: ricarica la pagina.")
        for pos, cid in enumerate(ids, 1):
            conn.execute("UPDATE category SET position=? WHERE id=? AND user_id=current_uid()", (pos, cid))
        conn.commit()
    return jsonify(ok=True)


@impostazioni_bp.route('/impostazioni/categoria/<int:cid>/elimina', methods=['POST'])
def delete_category(cid):
    """Elimina una categoria. Se ha spese (o regole ricorrenti) vanno riassegnate a un'altra categoria,
    scelta dall'utente (`target`): spese, regole ricorrenti e spese previste passano alla nuova categoria
    e, nelle spese e nelle regole, anche il tipo (necessità/extra) segue la nuova categoria."""
    with finance_db() as conn:
        cat = conn.execute("SELECT category FROM category WHERE id=? AND user_id=current_uid()", (cid,)).fetchone()
        if not cat:
            raise ValidationError('Categoria non trovata.')
        name = cat[0]
        used = {t: conn.execute(f"SELECT COUNT(*) FROM {t} WHERE user_id=current_uid() AND category=? COLLATE NOCASE", (name,)).fetchone()[0]
                for t in ('expenses', 'recurring_expenses', 'planned_expenses')}
        moved = ''
        if any(used.values()):
            raw = request.form.get('target', '')
            if not raw:
                raise ValidationError(f'«{name}» ha dei movimenti: scegli la categoria a cui spostarli.', 'target')
            tid = parse_id(raw, 'target')
            target = conn.execute("SELECT category, type FROM category WHERE id=? AND user_id=current_uid()", (tid,)).fetchone()
            if not target or tid == cid:
                raise ValidationError('Scegli un\'altra categoria di destinazione.', 'target')
            for table in ('expenses', 'recurring_expenses'):
                conn.execute(f"UPDATE {table} SET category=?, type=? WHERE user_id=current_uid() AND category=? COLLATE NOCASE",
                             (target[0], target[1], name))
            conn.execute("UPDATE planned_expenses SET category=? WHERE user_id=current_uid() AND category=? COLLATE NOCASE",
                         (target[0], name))
            moved = f' Spese spostate in «{target[0]}»: {used["expenses"]}.'
        conn.execute("DELETE FROM category WHERE id=? AND user_id=current_uid()", (cid,))
        conn.commit()
    flash(f'Categoria «{name}» eliminata.{moved}', 'success')
    return _back('categorie')


@impostazioni_bp.route('/impostazioni/save', methods=['POST'])
def save():
    with finance_db() as conn:
        cats = q(conn, "SELECT id FROM category WHERE user_id=current_uid()")
        for (cat_id,) in cats:
            raw = request.form.get(f'budget_{cat_id}', '0').replace(',', '.').strip() or '0'
            try:
                val = float(raw)
            except ValueError:
                val = 0.0
            conn.execute("UPDATE category SET budget=? WHERE id=? AND user_id=current_uid()", (val, cat_id))
        conn.commit()
    flash('Budget aggiornati.', 'success')
    return _back('categorie')


# ── Dati: importazione ed esportazione ───────────────────────────────────────

@impostazioni_bp.route('/impostazioni/importa', methods=['POST'])
def import_file():
    """Importa spese, entrate o patrimonio da un file CSV/TXT (formato in importer.py). Tutto o niente."""
    kind = request.form.get('tipo', '')
    if kind not in importer.FORMATS:
        raise ValidationError('Scegli cosa importare.', 'tipo')
    upload = request.files.get('file')
    if not upload or not upload.filename:
        raise ValidationError('Scegli un file da importare.', 'file')
    raw = upload.read(importer.MAX_BYTES + 1)
    header, rows = importer.read_table(raw)

    with finance_db() as conn:
        if kind == 'spese':
            cats = {r[0].lower(): (r[0], r[1]) for r in q(conn, "SELECT category, type FROM category WHERE user_id=current_uid()")}
            ok, errors = importer.parse_expenses(header, rows, cats)
        elif kind == 'entrate':
            ok, errors = importer.parse_incomes(header, rows)
        else:
            ok, errors = importer.parse_wealth(header, rows, wealth.config(conn))

        report = dict(kind=kind, filename=upload.filename, total=len(rows), errors=importer.summarize(errors),
                      n_errors=len(errors), added=0, skipped=0)
        if errors:                                   # tutto o niente: nessuna riga viene scritta
            return _render('dati', report)

        for r in ok:
            if kind == 'spese':
                dup = conn.execute("SELECT 1 FROM expenses WHERE user_id=current_uid() AND date=? AND euro=? AND category=? COLLATE NOCASE",
                                   (r['date'], r['euro'], r['category'])).fetchone()
                if not dup:
                    conn.execute("INSERT INTO expenses (date, euro, category, description, user_id, type) VALUES (?,?,?,?,current_uid(),?)",
                                 (r['date'], r['euro'], r['category'], r['description'], r['type']))
            elif kind == 'entrate':
                dup = conn.execute("SELECT 1 FROM incomes WHERE user_id=current_uid() AND date=? AND euro=? AND description=?",
                                   (r['date'], r['euro'], r['description'])).fetchone()
                if not dup:
                    conn.execute("INSERT INTO incomes (date, euro, description, user_id) VALUES (?,?,?,current_uid())",
                                 (r['date'], r['euro'], r['description']))
            else:
                dup = conn.execute("SELECT 1 FROM wealth_values WHERE user_id=current_uid() AND anno=? AND mese=?",
                                   (r['anno'], r['mese'])).fetchone()
                if not dup:
                    for code, value in r['values'].items():
                        conn.execute("INSERT INTO wealth_values (user_id, anno, mese, slot, value) VALUES (current_uid(),?,?,?,?)",
                                     (r['anno'], r['mese'], code, value))
            if dup:
                report['skipped'] += 1
            else:
                report['added'] += 1
        conn.commit()

    noun = {'spese': 'spese', 'entrate': 'entrate', 'patrimonio': 'mesi di patrimonio'}[kind]
    msg = f"Importati {report['added']} {noun}."
    if report['skipped']:
        msg += f" Già presenti e saltati: {report['skipped']}."
    flash(msg, 'success' if report['added'] else 'info')
    return _back('dati')


@impostazioni_bp.route('/impostazioni/export/patrimonio.csv')
def export_wealth():
    """Il patrimonio in CSV, nello stesso formato che l'importazione sa leggere."""
    with finance_db() as conn:
        text = importer.wealth_export(wealth.config(conn), wealth.months(conn))
    return Response(text, mimetype='text/csv',
                    headers={'Content-Disposition': f'attachment; filename="patrimonio_{datetime.today():%Y-%m-%d}.csv"'})


# ── Account ──────────────────────────────────────────────────────────────────

# Tabelle con i dati personali: tutte hanno `user_id`. Se ne aggiungi una nuova, aggiungila anche qui.
USER_TABLES = ('expenses', 'incomes', 'category', 'recurring_expenses', 'planned_expenses', 'budgets',
               'wealth_values', 'wealth_slots', 'wealth_group_settings', 'patrimonio')


def _check_account_password(conn, password, field):
    """Controlla la password dell'utente in sessione; rallenta chi sbaglia. ValidationError se è errata."""
    row = conn.execute('SELECT password_hash FROM users WHERE id=?', (g.user['id'],)).fetchone()
    if not row or not row[0] or not check_password_hash(row[0], password or ''):
        time.sleep(1)
        raise ValidationError('Password errata.', field)
    return row[0]


@impostazioni_bp.route('/impostazioni/account/password', methods=['POST'])
def change_password():
    new, again = request.form.get('new_password', ''), request.form.get('new_password2', '')
    with finance_db(user_id=0) as conn:                      # `users` non è una tabella personale: nessun filtro utente
        old_hash = _check_account_password(conn, request.form.get('current_password'), 'current_password')
        if len(new) < PASSWORD_MIN:
            raise ValidationError(f'La nuova password deve avere almeno {PASSWORD_MIN} caratteri.', 'new_password')
        if new != again:
            raise ValidationError('Le due password nuove non coincidono.', 'new_password2')
        if check_password_hash(old_hash, new):
            raise ValidationError('La nuova password è uguale a quella attuale.', 'new_password')
        new_hash = generate_password_hash(new)
        conn.execute('UPDATE users SET password_hash=? WHERE id=?', (new_hash, g.user['id']))
        conn.commit()
    # Cambiare password invalida le sessioni (l'impronta dipende dall'hash): questa resta valida, le altre no.
    session['fp'] = fingerprint(new_hash)
    flash('Password cambiata. Gli altri dispositivi dovranno rifare l\'accesso.', 'success')
    return _back('account')


@impostazioni_bp.route('/impostazioni/account/elimina', methods=['POST'])
def delete_account():
    """Elimina l'account e TUTTI i suoi dati, per sempre. Servono nome utente, password e una conferma esplicita."""
    if request.form.get('username', '').strip().lower() != g.user['username'].lower():
        raise ValidationError('Il nome utente scritto non coincide con il tuo.', 'username')
    if request.form.get('confirm') != '1':
        raise ValidationError('Spunta la casella per confermare che hai capito.', 'confirm')
    uid = g.user['id']
    with finance_db(user_id=0) as conn:
        _check_account_password(conn, request.form.get('password'), 'password')
        for table in USER_TABLES:
            conn.execute(f'DELETE FROM {table} WHERE user_id=?', (uid,))
        conn.execute('DELETE FROM users WHERE id=?', (uid,))
        conn.commit()
    session.clear()
    flash('Account eliminato, insieme a tutti i suoi dati.', 'success')
    return redirect(url_for('auth.login'))
