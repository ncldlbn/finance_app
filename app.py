import hashlib
import logging
import os
import uuid
from datetime import timedelta
from logging.handlers import RotatingFileHandler

from flask import Flask, flash, jsonify, redirect, render_template, request, url_for
from werkzeug.exceptions import HTTPException
from config import Config
from palette import P as _PALETTE
from validators import ValidationError


def create_app(config=Config):
    app = Flask(__name__)
    app.config.from_object(config)

    # Access control. In production (FINANCE_LOCAL unset) the app REFUSES TO START without a
    # password hash and a secret key, so it can never be served open by mistake.
    # FINANCE_LOCAL=1 is for local development / demo: no secure-cookie requirement, and no
    # login at all if no password hash is configured.
    local = os.environ.get('FINANCE_LOCAL') == '1'
    pw_hash = os.environ.get('APP_PASSWORD_HASH', '')
    if not local and not (pw_hash and config.SECRET_KEY):
        raise RuntimeError('APP_PASSWORD_HASH and SECRET_KEY must be set (see README, "Password"). '
                           'For local development set FINANCE_LOCAL=1.')
    app.secret_key = config.SECRET_KEY or 'dev-only-key'
    app.config.update(
        AUTH_ENABLED=bool(pw_hash),
        APP_PASSWORD_HASH=pw_hash,
        AUTH_FINGERPRINT=hashlib.sha256(pw_hash.encode()).hexdigest()[:20],  # changes with the password
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
        return {'PALETTE': _PALETTE, 'auth_enabled': app.config['AUTH_ENABLED'], 'asset_v': _asset_version()}

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
