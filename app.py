from flask import Flask
from config import Config
from palette import P as _PALETTE


def create_app(config=Config):
    app = Flask(__name__)
    app.config.from_object(config)
    app.secret_key = config.SECRET_KEY

    @app.context_processor
    def inject_palette():
        return {'PALETTE': _PALETTE}

    from blueprints.home import home_bp
    from blueprints.input import input_bp
    from blueprints.elenco import elenco_bp
    from blueprints.statistiche import statistiche_bp
    from blueprints.etf import etf_bp
    from blueprints.patrimonio import patrimonio_bp
    from blueprints.impostazioni import impostazioni_bp

    app.register_blueprint(home_bp)
    app.register_blueprint(input_bp)
    app.register_blueprint(elenco_bp)
    app.register_blueprint(statistiche_bp)
    app.register_blueprint(etf_bp)
    app.register_blueprint(patrimonio_bp)
    app.register_blueprint(impostazioni_bp)

    return app


if __name__ == "__main__":
    app = create_app()
    app.run(debug=True)
