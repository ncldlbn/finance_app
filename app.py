import hashlib
import os
from datetime import timedelta

from flask import Flask
from config import Config
from palette import P as _PALETTE


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

    @app.context_processor
    def inject_palette():
        return {'PALETTE': _PALETTE, 'auth_enabled': app.config['AUTH_ENABLED']}

    from blueprints.auth import auth_bp
    from blueprints.dashboard import dashboard_bp
    from blueprints.input import input_bp
    from blueprints.elenco import elenco_bp
    from blueprints.grafici import grafici_bp
    from blueprints.previste import previste_bp
    from blueprints.monitor import monitor_bp
    # from blueprints.etf import etf_bp  # disabilitata: non funziona su PythonAnywhere
    from blueprints.patrimonio import patrimonio_bp
    from blueprints.impostazioni import impostazioni_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(input_bp)
    app.register_blueprint(elenco_bp)
    app.register_blueprint(grafici_bp)
    app.register_blueprint(previste_bp)
    app.register_blueprint(monitor_bp)
    # app.register_blueprint(etf_bp)
    app.register_blueprint(patrimonio_bp)
    app.register_blueprint(impostazioni_bp)

    return app


if __name__ == "__main__":
    app = create_app()
    app.run(debug=True)
