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
  - Email: obbligatoria per i nuovi account e da verificare con un link (24 ore). Finché non è verificata si
    vede solo la pagina «controlla la tua email». Si accede con il nome utente oppure con l'email.
  - Password dimenticata: link via email valido un'ora e usabile una volta; la risposta è sempre la stessa, che
    l'account esista o no. Dei codici (verifica e recupero) il database conserva solo l'impronta SHA-256.
"""
import hashlib
import hmac
import re
import secrets
import time
from datetime import date
from urllib.parse import urlparse

from flask import (Blueprint, current_app, flash, g, jsonify, redirect, render_template, request, session,
                   url_for)
from werkzeug.security import check_password_hash, generate_password_hash

import demo_data
import mailer
from db import connect_raw, finance_db

auth_bp = Blueprint('auth', __name__)

MAX_FAILS = 5
WINDOW = 15 * 60  # secondi
SAFE_METHODS = ('GET', 'HEAD', 'OPTIONS')
PUBLIC_ENDPOINTS = ('auth.login', 'auth.register', 'auth.forgot', 'auth.reset_password', 'auth.verify_email', 'static')
# Le sole pagine di chi non ha ancora verificato l'email.
VERIFY_ALLOWED = ('auth.logout', 'auth.verify_pending', 'auth.resend_verification', 'impostazioni.change_email')
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
            row = conn.execute('SELECT id, username, is_demo, password_hash, theme, email, email_verified FROM users WHERE id=?',
                               (uid,)).fetchone()
        if row and hmac.compare_digest(str(fp or ''), fingerprint(row[3])):
            return {'id': row[0], 'username': row[1], 'is_demo': bool(row[2]), 'theme': row[4],
                    'email': row[5], 'email_verified': bool(row[6])}
    if current_app.config['LOCAL_NO_LOGIN']:
        return {'id': 1, 'username': 'locale', 'is_demo': False, 'theme': 'auto', 'email': '', 'email_verified': False}
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
    if g.user['email'] and not g.user['email_verified'] and request.endpoint not in VERIFY_ALLOWED:
        return redirect(url_for('auth.verify_pending'))        # account nuovo: prima si verifica l'email
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
            row = _find_user(conn, username, 'id, password_hash, is_demo')     # nome utente oppure email
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


EMAIL_RE = re.compile(r'^[^@\s<>"(),;:]+@[^@\s<>"(),;:]+\.[a-z]{2,}$')
TOKEN_TTL = {'verify': 24 * 3600, 'reset': 3600}         # secondi
MAX_MAILS = 5                                            # email per indirizzo IP e per account, nella finestra WINDOW


def mail_ready():
    """Si possono mandare email (SMTP configurato, o modalità locale dove finiscono nel log)."""
    return current_app.config.get('MAIL_READY', False)


def registration_open():
    return (current_app.config.get('REGISTRATION_OPEN', True) and not current_app.config['LOCAL_NO_LOGIN']
            and mail_ready())                            # senza email non si può verificare l'indirizzo


def normalize_email(raw):
    """Indirizzo in minuscolo se ha una forma valida, altrimenti None."""
    email = (raw or '').strip().lower()
    return email if len(email) <= 254 and EMAIL_RE.match(email) else None


def _find_user(conn, ident, cols):
    """Utente per nome utente oppure (se c'è una @) per email; senza distinguere le maiuscole."""
    if '@' in ident:
        return conn.execute(f"SELECT {cols} FROM users WHERE email=? COLLATE NOCASE AND email != ''", (ident,)).fetchone()
    return conn.execute(f'SELECT {cols} FROM users WHERE username=? COLLATE NOCASE', (ident,)).fetchone()


def rate_hit(conn, key, limit):
    """Conta un tentativo per `key` nella finestra WINDOW; True se il limite era già raggiunto (e non lo conta)."""
    now = time.time()
    conn.execute('DELETE FROM login_attempts WHERE ts < ?', (now - WINDOW,))
    if conn.execute('SELECT COUNT(*) FROM login_attempts WHERE ip=?', (key,)).fetchone()[0] >= limit:
        return True
    conn.execute('INSERT INTO login_attempts (ip, ts) VALUES (?, ?)', (key, now))
    return False


# ── Codici monouso (verifica dell'email, recupero della password) ────────────

def _token_hash(raw):
    return hashlib.sha256(raw.encode()).hexdigest()


def issue_token(conn, user_id, kind, email=''):
    """Nuovo codice (vale solo l'ultimo: quelli precedenti dello stesso tipo smettono di valere)."""
    raw, now = secrets.token_urlsafe(32), time.time()
    conn.execute('DELETE FROM auth_tokens WHERE (user_id=? AND kind=? AND used=0) OR expires < ?',
                 (user_id, kind, now - 7 * 86400))
    conn.execute('INSERT INTO auth_tokens (user_id, kind, token_hash, email, expires, created) VALUES (?,?,?,?,?,?)',
                 (user_id, kind, _token_hash(raw), email, now + TOKEN_TTL[kind], now))
    return raw


def find_token(conn, raw, kind):
    """(id, user_id, email) di un codice valido (giusto tipo, non usato, non scaduto), altrimenti None."""
    if not raw or len(raw) > 100:
        return None
    return conn.execute('SELECT id, user_id, email FROM auth_tokens WHERE token_hash=? AND kind=? AND used=0 AND expires > ?',
                        (_token_hash(raw), kind, time.time())).fetchone()


def consume_token(conn, token_id):
    """Segna il codice come usato; False se nel frattempo l'aveva già usato un'altra richiesta."""
    return conn.execute('UPDATE auth_tokens SET used=1 WHERE id=? AND used=0', (token_id,)).rowcount == 1


def _mail_link(endpoint, **values):
    """Link assoluto per un'email: da APP_BASE_URL, mai dall'host della richiesta (falsificabile)."""
    base = mailer.base_url()
    return base + url_for(endpoint, **values) if base else url_for(endpoint, _external=True, **values)


def _send(template, to, subject, **ctx):
    mailer.send(to, subject, render_template(f'email/{template}.txt', **ctx),
                render_template(f'email/{template}.html', subject=subject, **ctx))


def send_verification(conn, user_id, username, email):
    """Codice di verifica per `email` (anche un indirizzo nuovo, che diventa quello dell'account solo dopo la
    conferma) e invio del link. Fa commit. Solleva mailer.MailError se l'email non parte."""
    raw = issue_token(conn, user_id, 'verify', email)
    conn.commit()
    _send('verify', email, 'Conferma il tuo indirizzo email', username=username,
          link=_mail_link('auth.verify_email', token=raw), hours=TOKEN_TTL['verify'] // 3600)


@auth_bp.route('/registrati', methods=['GET', 'POST'])
def register():
    if not registration_open():
        flash('La registrazione non è attiva.', 'warning')
        return redirect(url_for('auth.login'))
    if request.method == 'GET' and _load_user():
        return redirect(url_for('dashboard.index'))

    error, username, email_raw = None, '', ''
    if request.method == 'POST':
        if not _origin_ok():
            return render_template('error.html', code=400, title='Richiesta non valida',
                                   text='La richiesta non proviene da questo sito. Ricarica la pagina e riprova.'), 400
        username = request.form.get('username', '').strip().lower()
        email_raw = request.form.get('email', '').strip()
        email = normalize_email(email_raw)
        pw, pw2 = request.form.get('password', ''), request.form.get('password2', '')
        key, now = 'reg:' + _client_ip(), time.time()
        with finance_db(user_id=0) as conn:
            conn.execute('DELETE FROM login_attempts WHERE ts < ?', (now - WINDOW,))
            if conn.execute('SELECT COUNT(*) FROM login_attempts WHERE ip=?', (key,)).fetchone()[0] >= MAX_SIGNUPS:
                conn.commit()
                return render_template('register.html', error='Troppe registrazioni da questo indirizzo. Riprova tra qualche minuto.',
                                       username=username, email=email_raw), 429
            if not USERNAME_RE.match(username):
                error = 'Il nome utente deve avere 3-40 caratteri: lettere, numeri, punto, trattino o trattino basso.'
            elif not email:
                error = 'Indirizzo email non valido.'
            elif len(pw) < PASSWORD_MIN:
                error = f'La password deve avere almeno {PASSWORD_MIN} caratteri.'
            elif pw != pw2:
                error = 'Le due password non coincidono.'
            elif conn.execute('SELECT 1 FROM users WHERE username=? COLLATE NOCASE', (username,)).fetchone():
                error = 'Nome utente già in uso.'
            elif conn.execute("SELECT 1 FROM users WHERE email=? COLLATE NOCASE AND email != ''", (email,)).fetchone():
                error = 'Questo indirizzo email è già usato da un altro account.'
            conn.execute('INSERT INTO login_attempts (ip, ts) VALUES (?, ?)', (key, now))
            if error is None:
                h = generate_password_hash(pw)
                new_id = conn.execute('INSERT INTO users (username, password_hash, is_demo, email, email_verified) '
                                      'VALUES (?,?,0,?,0) RETURNING id', (username, h, email)).fetchone()[0]
                conn.commit()
                with finance_db(user_id=new_id) as user_conn:   # le categorie di partenza appartengono al nuovo utente
                    demo_data.seed_categories(user_conn, new_id)
                    user_conn.commit()
                session.clear()
                session['uid'], session['fp'] = new_id, fingerprint(h)
                session.permanent = True
                try:
                    send_verification(conn, new_id, username, email)
                except mailer.MailError:
                    flash("Account creato, ma l'email di conferma non è partita: riprova con «Mandami di nuovo il link».", 'warning')
                return redirect(url_for('auth.verify_pending'))
            conn.commit()
    return render_template('register.html', error=error, username=username, email=email_raw)


# ── Verifica dell'email ──────────────────────────────────────────────────────

@auth_bp.route('/verifica-email')
def verify_pending():
    """Pagina «controlla la tua email»: l'unica (con logout) di chi non ha ancora verificato l'indirizzo."""
    if not (g.user['email'] and not g.user['email_verified']):
        return redirect(url_for('dashboard.index'))
    return render_template('verify_pending.html', email=g.user['email'], hours=TOKEN_TTL['verify'] // 3600)


@auth_bp.route('/verifica-email/reinvia', methods=['POST'])
def resend_verification():
    if not (g.user['email'] and not g.user['email_verified']):
        return redirect(url_for('dashboard.index'))
    with finance_db(user_id=0) as conn:
        if rate_hit(conn, f"mail:u:{g.user['id']}", MAX_MAILS):
            conn.commit()
            flash('Hai chiesto troppe email: riprova tra qualche minuto.', 'warning')
            return redirect(url_for('auth.verify_pending'))
        try:
            send_verification(conn, g.user['id'], g.user['username'], g.user['email'])
            flash(f"Ti abbiamo mandato un nuovo link a {g.user['email']}.", 'success')
        except mailer.MailError:
            flash("L'email non è partita: riprova tra qualche minuto.", 'error')
    return redirect(url_for('auth.verify_pending'))


@auth_bp.route('/verifica-email/<token>')
def verify_email(token):
    """Link dell'email di verifica: l'indirizzo del codice diventa quello (verificato) dell'account."""
    user = _load_user()
    back = url_for('dashboard.index') if user else url_for('auth.login')
    with finance_db(user_id=0) as conn:
        tok = find_token(conn, token, 'verify')
        if not tok:
            flash('Il link non è valido o è scaduto. Se serve, chiedine uno nuovo.', 'warning')
            return redirect(back)
        token_id, uid, email = tok
        if conn.execute("SELECT 1 FROM users WHERE email=? COLLATE NOCASE AND id != ?", (email, uid)).fetchone():
            consume_token(conn, token_id)
            conn.commit()
            flash('Questo indirizzo email è già usato da un altro account.', 'error')
            return redirect(back)
        if consume_token(conn, token_id):
            conn.execute('UPDATE users SET email=?, email_verified=1 WHERE id=?', (email, uid))
            conn.execute("DELETE FROM auth_tokens WHERE user_id=? AND kind='verify' AND used=0", (uid,))
        conn.commit()
    flash(f'Indirizzo {email} verificato.', 'success')
    return redirect(back)


# ── Password dimenticata ─────────────────────────────────────────────────────

@auth_bp.route('/password-dimenticata', methods=['GET', 'POST'])
def forgot():
    """Chiede il nome utente o l'email e, se l'account esiste e ha un'email, manda il link. La risposta è sempre
    la stessa: la pagina non rivela chi è registrato."""
    if not mail_ready():
        return render_template('forgot.html', unavailable=True)
    sent = False
    if request.method == 'POST':
        if not _origin_ok():
            return render_template('error.html', code=400, title='Richiesta non valida',
                                   text='La richiesta non proviene da questo sito. Ricarica la pagina e riprova.'), 400
        ident = request.form.get('ident', '').strip().lower()[:254]
        with finance_db(user_id=0) as conn:
            if rate_hit(conn, 'mail:' + _client_ip(), MAX_MAILS):
                conn.commit()
                return render_template('forgot.html', error='Troppe richieste da questo indirizzo. Riprova tra qualche minuto.'), 429
            row = _find_user(conn, ident, 'id, username, email, is_demo') if ident else None
            if row and row[2] and not row[3] and not rate_hit(conn, f'mail:u:{row[0]}', MAX_MAILS):
                raw = issue_token(conn, row[0], 'reset')
                conn.commit()
                try:
                    _send('reset', row[2], 'Reimposta la password', username=row[1],
                          link=_mail_link('auth.reset_password', token=raw), minutes=TOKEN_TTL['reset'] // 60)
                except mailer.MailError:
                    pass                                 # già nel log; la risposta resta uguale
            conn.commit()
        sent = True
    return render_template('forgot.html', sent=sent)


@auth_bp.route('/password-nuova/<token>', methods=['GET', 'POST'])
def reset_password(token):
    """Link dell'email di recupero: nuova password. Il codice vale una volta; dopo il cambio tutte le sessioni
    aperte smettono di valere (dipendono dall'hash della password)."""
    error = None
    with finance_db(user_id=0) as conn:
        tok = find_token(conn, token, 'reset')
        if not tok:
            return render_template('reset.html', invalid=True), 400
        if request.method == 'POST':
            if not _origin_ok():
                return render_template('error.html', code=400, title='Richiesta non valida',
                                       text='La richiesta non proviene da questo sito. Ricarica la pagina e riprova.'), 400
            pw, pw2 = request.form.get('password', ''), request.form.get('password2', '')
            if len(pw) < PASSWORD_MIN:
                error = f'La password deve avere almeno {PASSWORD_MIN} caratteri.'
            elif pw != pw2:
                error = 'Le due password non coincidono.'
            elif not consume_token(conn, tok[0]):
                return render_template('reset.html', invalid=True), 400
            else:
                # Aver ricevuto il link prova che l'email è sua: se non era ancora verificata, ora lo è.
                conn.execute('UPDATE users SET password_hash=?, email_verified=1 WHERE id=?',
                             (generate_password_hash(pw), tok[1]))
                conn.execute("DELETE FROM auth_tokens WHERE user_id=? AND kind='reset' AND used=0", (tok[1],))
                conn.commit()
                session.clear()
                flash('Password cambiata: accedi con quella nuova. Le sessioni aperte sugli altri dispositivi sono chiuse.', 'success')
                return redirect(url_for('auth.login'))
    return render_template('reset.html', error=error, invalid=False)
