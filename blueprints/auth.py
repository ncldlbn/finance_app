"""Accesso multiutente: nome utente + password, uno per persona.

  - Gli utenti stanno nella tabella `users` (hash della password, mai la password). Si creano dalla pagina
    /registrati (spegnibile con REGISTRATION_OPEN=0) oppure con `scripts/add_user.py`.
  - Tutte le pagine richiedono la sessione, tranne /login e i file statici. La sessione è un cookie firmato,
    persistente (1 anno, rinnovato a ogni visita). Contiene l'id utente e un'impronta dell'hash della password:
    cambiando password le sessioni di quell'utente smettono di valere.
  - `g.user` è l'utente della richiesta; `db.finance_db()` ne fa l'ambito di ogni interrogazione (`current_uid()`).
  - Account demo (`is_demo`): dati fittizi, che si rigenerano una volta al giorno, e SOLA LETTURA.
  - Protezione dei moduli: ogni richiesta che modifica dati deve arrivare da questo stesso sito (controllo di
    Origin/Referer), oltre al cookie `SameSite=Lax`.
  - Dopo 5 tentativi sbagliati in 15 minuti, per lo stesso indirizzo o per lo stesso nome utente, il login
    risponde 429 finché non passa la finestra.
"""
import hashlib
import hmac
import re
import time
from datetime import date
from urllib.parse import urlparse

from flask import (Blueprint, current_app, flash, g, jsonify, redirect, render_template, request, session,
                   url_for)
from werkzeug.security import check_password_hash, generate_password_hash

import demo_data
from db import connect_raw, finance_db

auth_bp = Blueprint('auth', __name__)

MAX_FAILS = 5
WINDOW = 15 * 60  # secondi
SAFE_METHODS = ('GET', 'HEAD', 'OPTIONS')
PUBLIC_ENDPOINTS = ('auth.login', 'auth.register', 'static')
_DUMMY_HASH = generate_password_hash('password-finta-per-tempi-costanti')   # per non rivelare se un utente esiste


def fingerprint(password_hash):
    return hashlib.sha256(password_hash.encode()).hexdigest()[:20]


def _client_ip():
    # Dietro il proxy l'indirizzo reale arriva in X-Forwarded-For.
    forwarded = request.headers.get('X-Forwarded-For', '')
    return (forwarded.split(',')[0].strip() if forwarded else request.remote_addr) or '?'


def _safe_next(target):
    """Solo percorsi interni: niente redirect verso altri siti dopo il login."""
    if target and target.startswith('/') and not target.startswith('//') and '\\' not in target:
        return target
    return url_for('dashboard.index')


def _same_site_back():
    ref = request.referrer or ''
    return ref if urlparse(ref).netloc == request.host else url_for('dashboard.index')


def _load_user():
    """Utente della sessione (o None). In modalità locale senza utenti registrati si entra come utente 1."""
    uid, fp = session.get('uid'), session.get('fp')
    if uid:
        with connect_raw() as conn:
            row = conn.execute('SELECT id, username, is_demo, password_hash, theme FROM users WHERE id=?', (uid,)).fetchone()
        if row and hmac.compare_digest(str(fp or ''), fingerprint(row[3])):
            return {'id': row[0], 'username': row[1], 'is_demo': bool(row[2]), 'theme': row[4]}
    if current_app.config['LOCAL_NO_LOGIN']:
        return {'id': 1, 'username': 'locale', 'is_demo': False, 'theme': 'auto'}
    return None


def _origin_ok():
    """Le richieste che modificano dati devono arrivare da questo sito. Con Origin presente deve coincidere con
    l'host; in sua assenza si guarda il Referer; se mancano entrambi si rifiuta (tranne in modalità locale)."""
    for header in ('Origin', 'Referer'):
        value = request.headers.get(header)
        if value:
            return urlparse(value).netloc == request.host
    return current_app.config['LOCAL_NO_LOGIN'] or current_app.config.get('CSRF_LENIENT', False)


@auth_bp.before_app_request
def require_login():
    g.user = None
    if request.endpoint in PUBLIC_ENDPOINTS:
        return None
    g.user = _load_user()
    if g.user is None:
        if request.method in SAFE_METHODS:
            return redirect(url_for('auth.login', next=request.full_path.rstrip('?')))
        return redirect(url_for('auth.login'))
    if request.method not in SAFE_METHODS:
        if not _origin_ok():
            current_app.logger.warning('Richiesta rifiutata (origine non valida): %s %s', request.method, request.path)
            return render_template('error.html', code=400, title='Richiesta non valida',
                                   text='La richiesta non proviene da questo sito. Ricarica la pagina e riprova.'), 400
        if g.user['is_demo'] and request.endpoint != 'auth.logout':
            msg = "L'account demo è in sola lettura: nessuna modifica viene salvata."
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify(error=msg), 403
            flash(msg, 'warning')
            return redirect(_same_site_back())
    return None


def refresh_demo_if_stale(conn, user_id):
    """I dati dell'account demo sono relativi a oggi: si rigenerano una volta al giorno."""
    today = date.today()
    row = conn.execute('SELECT data_date FROM users WHERE id=?', (user_id,)).fetchone()
    if row and row[0] != today.isoformat():
        demo_data.populate(conn, user_id, today)
        conn.execute('UPDATE users SET data_date=? WHERE id=?', (today.isoformat(), user_id))
        conn.commit()


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_app.config['LOCAL_NO_LOGIN'] or (request.method == 'GET' and _load_user()):
        return redirect(url_for('dashboard.index'))

    error = None
    if request.method == 'POST':
        username = request.form.get('username', '').strip().lower()[:80]
        keys = (_client_ip(), 'u:' + username)             # si limita sia l'indirizzo sia il nome utente
        now = time.time()
        with finance_db(user_id=0) as conn:                # nessun dato personale: l'id 0 non corrisponde a nessuno
            conn.execute('DELETE FROM login_attempts WHERE ts < ?', (now - WINDOW,))
            fails = max(conn.execute('SELECT COUNT(*) FROM login_attempts WHERE ip=?', (k,)).fetchone()[0] for k in keys)
            if fails >= MAX_FAILS:
                conn.commit()
                return render_template('login.html', error='Troppi tentativi. Riprova tra qualche minuto.'), 429
            row = conn.execute('SELECT id, password_hash, is_demo FROM users WHERE username=? COLLATE NOCASE', (username,)).fetchone()
            has_pw = bool(row and row[1])               # un utente senza password non può accedere
            ok = check_password_hash(row[1] if has_pw else _DUMMY_HASH, request.form.get('password', '')) and has_pw
            if ok:
                conn.execute('DELETE FROM login_attempts WHERE ip IN (?, ?)', keys)
                conn.commit()
                if row[2]:                                  # dati del demo: connessione dell'utente demo
                    with finance_db(user_id=row[0]) as demo_conn:   # (con PostgreSQL la Row-Level Security lo esige)
                        refresh_demo_if_stale(demo_conn, row[0])
                session.clear()
                session['uid'], session['fp'] = row[0], fingerprint(row[1])
                session.permanent = True
                return redirect(_safe_next(request.args.get('next')))
            conn.executemany('INSERT INTO login_attempts (ip, ts) VALUES (?, ?)', [(k, now) for k in keys])
            conn.commit()
        time.sleep(1)  # rallenta chi prova password a raffica
        error = 'Nome utente o password errati.'
    return render_template('login.html', error=error)


@auth_bp.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('auth.login'))


USERNAME_RE = re.compile(r'^[a-z0-9._-]{3,40}$')
PASSWORD_MIN = 8
MAX_SIGNUPS = 5                                          # per indirizzo, nella finestra WINDOW


def registration_open():
    return current_app.config.get('REGISTRATION_OPEN', True) and not current_app.config['LOCAL_NO_LOGIN']


@auth_bp.route('/registrati', methods=['GET', 'POST'])
def register():
    if not registration_open():
        flash('La registrazione non è attiva.', 'warning')
        return redirect(url_for('auth.login'))
    if request.method == 'GET' and _load_user():
        return redirect(url_for('dashboard.index'))

    error, username = None, ''
    if request.method == 'POST':
        if not _origin_ok():
            return render_template('error.html', code=400, title='Richiesta non valida',
                                   text='La richiesta non proviene da questo sito. Ricarica la pagina e riprova.'), 400
        username = request.form.get('username', '').strip().lower()
        pw, pw2 = request.form.get('password', ''), request.form.get('password2', '')
        key, now = 'reg:' + _client_ip(), time.time()
        with finance_db(user_id=0) as conn:
            conn.execute('DELETE FROM login_attempts WHERE ts < ?', (now - WINDOW,))
            if conn.execute('SELECT COUNT(*) FROM login_attempts WHERE ip=?', (key,)).fetchone()[0] >= MAX_SIGNUPS:
                conn.commit()
                return render_template('register.html', error='Troppe registrazioni da questo indirizzo. Riprova tra qualche minuto.',
                                       username=username), 429
            if not USERNAME_RE.match(username):
                error = 'Il nome utente deve avere 3-40 caratteri: lettere, numeri, punto, trattino o trattino basso.'
            elif len(pw) < PASSWORD_MIN:
                error = f'La password deve avere almeno {PASSWORD_MIN} caratteri.'
            elif pw != pw2:
                error = 'Le due password non coincidono.'
            elif conn.execute('SELECT 1 FROM users WHERE username=? COLLATE NOCASE', (username,)).fetchone():
                error = 'Nome utente già in uso.'
            conn.execute('INSERT INTO login_attempts (ip, ts) VALUES (?, ?)', (key, now))
            if error is None:
                h = generate_password_hash(pw)
                new_id = conn.execute('INSERT INTO users (username, password_hash, is_demo) VALUES (?,?,0) RETURNING id',
                                      (username, h)).fetchone()[0]
                conn.commit()
                with finance_db(user_id=new_id) as user_conn:   # le categorie di partenza appartengono al nuovo utente
                    demo_data.seed_categories(user_conn, new_id)
                    user_conn.commit()
                session.clear()
                session['uid'], session['fp'] = new_id, fingerprint(h)
                session.permanent = True
                flash('Account creato. Le categorie di partenza si modificano in Impostazioni.', 'success')
                return redirect(url_for('dashboard.index'))
            conn.commit()
    return render_template('register.html', error=error, username=username)
