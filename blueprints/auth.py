"""Login con una sola password.

Tutte le pagine richiedono la sessione, tranne /login e i file statici. La
sessione è un cookie firmato, persistente (1 anno, rinnovato a ogni visita),
quindi la password si inserisce una volta per dispositivo.

  - La password non sta nel codice né nel database: solo il suo hash, in
    APP_PASSWORD_HASH (vedi scripts/set_password.py).
  - Il cookie contiene un'impronta dell'hash: cambiando password tutte le
    sessioni esistenti smettono di valere.
  - Dopo 5 tentativi sbagliati in 15 minuti da uno stesso indirizzo, il login
    risponde 429 finché non passa la finestra.
"""
from flask import Blueprint, render_template, request, redirect, url_for, session, current_app
import hmac
import time

from werkzeug.security import check_password_hash

from db import finance_db

auth_bp = Blueprint('auth', __name__)

MAX_FAILS = 5
WINDOW = 15 * 60  # secondi


def _client_ip():
    # Dietro il proxy di PythonAnywhere l'indirizzo reale arriva in X-Forwarded-For.
    forwarded = request.headers.get('X-Forwarded-For', '')
    return (forwarded.split(',')[0].strip() if forwarded else request.remote_addr) or '?'


def _safe_next(target):
    """Solo percorsi interni: niente redirect verso altri siti dopo il login."""
    if target and target.startswith('/') and not target.startswith('//') and '\\' not in target:
        return target
    return url_for('dashboard.index')


def _logged_in():
    return hmac.compare_digest(str(session.get('auth', '')), current_app.config['AUTH_FINGERPRINT'])


@auth_bp.before_app_request
def require_login():
    if not current_app.config['AUTH_ENABLED']:
        return None
    if request.endpoint in ('auth.login', 'static') or _logged_in():
        return None
    return redirect(url_for('auth.login', next=request.full_path.rstrip('?')))


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if not current_app.config['AUTH_ENABLED'] or (request.method == 'GET' and _logged_in()):
        return redirect(url_for('dashboard.index'))

    error = None
    if request.method == 'POST':
        ip, now = _client_ip(), time.time()
        with finance_db() as conn:
            conn.execute("DELETE FROM login_attempts WHERE ts < ?", (now - WINDOW,))
            fails = conn.execute("SELECT COUNT(*) FROM login_attempts WHERE ip=?", (ip,)).fetchone()[0]
            if fails >= MAX_FAILS:
                conn.commit()
                return render_template('login.html', error='Troppi tentativi. Riprova tra qualche minuto.'), 429
            if check_password_hash(current_app.config['APP_PASSWORD_HASH'], request.form.get('password', '')):
                conn.execute("DELETE FROM login_attempts WHERE ip=?", (ip,))
                conn.commit()
                session.clear()
                session['auth'] = current_app.config['AUTH_FINGERPRINT']
                session.permanent = True
                return redirect(_safe_next(request.args.get('next')))
            conn.execute("INSERT INTO login_attempts (ip, ts) VALUES (?, ?)", (ip, now))
            conn.commit()
        time.sleep(1)  # rallenta chi prova password a raffica
        error = 'Password errata.'
    return render_template('login.html', error=error)


@auth_bp.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('auth.login'))
