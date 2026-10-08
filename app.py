import logging
import os
import sqlite3
import uuid
from datetime import timedelta
from logging.handlers import RotatingFileHandler

from flask import Flask, flash, g, has_request_context, jsonify, redirect, render_template, request, url_for
from werkzeug.exceptions import HTTPException
from config import Config
from palette import P as _PALETTE
from validators import ValidationError


def _bootstrap_owner():
    """Garantisce che il proprietario (utente 1) possa accedere e ritorna quanti utenti hanno una password.

    Continuità con la versione a password unica: se `APP_PASSWORD_HASH` è impostata, diventa la password
    dell'utente 1 quando questo non ne ha ancora una (o lo crea, col nome `APP_USERNAME`, di default 'admin').
    Dopo di che il database è l'unica fonte di verità: la variabile non sovrascrive mai una password esistente."""
    from migrations import migrate
    migrate(Config.FINANCE_DB)                       # schema aggiornato prima di tutto (crea il database se manca)
    pw_hash = os.environ.get('APP_PASSWORD_HASH', '')
    with sqlite3.connect(Config.FINANCE_DB) as conn:
        owner = conn.execute('SELECT id, password_hash FROM users WHERE id=1').fetchone()
        if pw_hash and not owner:
            conn.execute('INSERT INTO users (id, username, password_hash) VALUES (1, ?, ?)',
                         (os.environ.get('APP_USERNAME', 'admin').strip().lower(), pw_hash))
        elif pw_hash and owner and not owner[1]:
            conn.execute('UPDATE users SET password_hash=? WHERE id=1', (pw_hash,))
            if os.environ.get('APP_USERNAME'):
                conn.execute('UPDATE users SET username=? WHERE id=1', (os.environ['APP_USERNAME'].strip().lower(),))
        return conn.execute("SELECT COUNT(*) FROM users WHERE password_hash != ''").fetchone()[0]


def create_app(config=Config):
    app = Flask(__name__)
    app.config.from_object(config)

    # Accesso. In produzione (FINANCE_LOCAL non impostato) l'app SI RIFIUTA DI PARTIRE senza SECRET_KEY e senza
    # almeno un utente con password: così non può mai essere servita aperta per errore.
    # FINANCE_LOCAL=1 è per sviluppo e demo: i cookie non richiedono HTTPS e, se non esiste nessun utente,
    # si entra direttamente come utente 1 senza login.
    local = os.environ.get('FINANCE_LOCAL') == '1'
    if not local and not config.SECRET_KEY:
        raise RuntimeError('SECRET_KEY deve essere impostata (vedi README, "Utenti e accesso"). '
                           'Per lo sviluppo in locale imposta FINANCE_LOCAL=1.')
    n_users = _bootstrap_owner()
    if not local and n_users == 0:
        raise RuntimeError('Nessun utente con password. Crea il primo con `python scripts/add_user.py <nome>` '
                           'oppure imposta APP_PASSWORD_HASH (e, se vuoi, APP_USERNAME): vedi README.')
    app.secret_key = config.SECRET_KEY or 'dev-only-key'
    app.config.update(
        LOCAL_NO_LOGIN=local and n_users == 0,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE='Lax',
        SESSION_COOKIE_SECURE=not local,
        PERMANENT_SESSION_LIFETIME=timedelta(days=365),
    )

    # I file statici si possono tenere in cache a lungo: il parametro ?v= (data di modifica) cambia
    # quando CSS o JS cambiano, quindi dopo un aggiornamento il browser scarica subito la versione nuova.
    app.config['SEND_FILE_MAX_AGE_DEFAULT'] = timedelta(days=30)
    static_dir = os.path.join(app.root_path, 'static')

    def _asset_version():
        try:
            return int(max(os.path.getmtime(os.path.join(static_dir, f)) for f in ('css/style.css', 'js/main.js')))
        except OSError:
            return 0

    @app.context_processor
    def inject_palette():
        return {'PALETTE': _PALETTE, 'asset_v': _asset_version(),
                'current_user': g.user if has_request_context() else None}

    # Compressione delle risposte (pagine fino a ~120 KB): attiva se Flask-Compress è installato.
    try:
        from flask_compress import Compress
        Compress(app)
    except ImportError:
        pass

    from blueprints.auth import auth_bp
    from blueprints.dashboard import dashboard_bp
    from blueprints.input import input_bp
    from blueprints.elenco import elenco_bp
    from blueprints.grafici import grafici_bp
    from blueprints.previste import previste_bp
    from blueprints.monitor import monitor_bp
    from blueprints.patrimonio import patrimonio_bp
    from blueprints.impostazioni import impostazioni_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(input_bp)
    app.register_blueprint(elenco_bp)
    app.register_blueprint(grafici_bp)
    app.register_blueprint(previste_bp)
    app.register_blueprint(monitor_bp)
    app.register_blueprint(patrimonio_bp)
    app.register_blueprint(impostazioni_bp)

    _setup_logging(app)
    _register_error_handlers(app)
    return app


def _setup_logging(app):
    """Log su stderr e su file a rotazione (LOG_DIR, di default ./logs; LOG_LEVEL, di default INFO).
    Su PythonAnywhere lo stderr finisce nell'error log dell'app, il file resta consultabile a parte."""
    level = getattr(logging, os.environ.get('LOG_LEVEL', 'INFO').upper(), logging.INFO)
    fmt = logging.Formatter('%(asctime)s %(levelname)s %(name)s: %(message)s')
    app.logger.setLevel(level)
    app.logger.propagate = False
    if not any(isinstance(h, logging.StreamHandler) for h in app.logger.handlers):
        h = logging.StreamHandler(); h.setFormatter(fmt); app.logger.addHandler(h)
    log_dir = os.environ.get('LOG_DIR', os.path.join(app.root_path, 'logs'))
    try:
        os.makedirs(log_dir, exist_ok=True)
        fh = RotatingFileHandler(os.path.join(log_dir, 'app.log'), maxBytes=1_000_000, backupCount=5, encoding='utf-8')
        fh.setFormatter(fmt); app.logger.addHandler(fh)
    except OSError:
        app.logger.warning('Log su file non disponibile in %s: si usa solo stderr', log_dir)


def _same_site_back():
    """Pagina da cui arriva l'utente, se è di questo sito (mai un indirizzo esterno)."""
    ref = request.referrer or ''
    return ref if ref.startswith(request.host_url) else url_for('dashboard.index')


def _register_error_handlers(app):
    @app.errorhandler(ValidationError)
    def validation_error(e):
        # Dato non valido in un modulo: messaggio (toast), campo evidenziato, si torna al modulo.
        app.logger.info('Validazione: %s (%s %s)', e.message, request.method, request.path)
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify(error=e.message, field=e.field), 400
        flash(e.message, f'error:{e.field}' if e.field else 'error')
        return redirect(_same_site_back())

    @app.errorhandler(HTTPException)
    def http_error(e):
        titles = {400: 'Richiesta non valida', 403: 'Accesso negato', 404: 'Pagina non trovata',
                  405: 'Operazione non consentita', 413: 'Dati troppo grandi', 429: 'Troppe richieste'}
        if e.code >= 500:
            return server_error(e)
        return render_template('error.html', code=e.code, title=titles.get(e.code, e.name),
                               text=e.description if e.code != 404 else 'L\'indirizzo non esiste o non è più valido.'), e.code

    @app.errorhandler(Exception)
    def server_error(e):
        ref = uuid.uuid4().hex[:8]
        # Il riferimento compare nella pagina e nel log: serve a ritrovare l'errore giusto.
        app.logger.error('Errore %s su %s %s', ref, request.method, request.path, exc_info=getattr(e, 'original_exception', e))
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.path.endswith('.json'):
            return jsonify(error='Errore interno del server.', ref=ref), 500
        # Pagina autonoma (non estende base.html): deve funzionare anche se l'errore è nel layout.
        return render_template('error500.html', ref=ref), 500


if __name__ == "__main__":
    app = create_app()
    app.run(debug=True)
