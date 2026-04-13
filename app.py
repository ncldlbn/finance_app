from flask import Flask
from config import Config


def create_app(config=Config):
    app = Flask(__name__)
    app.config.from_object(config)
    app.secret_key = config.SECRET_KEY

    from blueprints.home import home_bp
    from blueprints.input import input_bp
    from blueprints.elenco import elenco_bp
    from blueprints.bilancio import bilancio_bp
    from blueprints.statistiche import statistiche_bp
    from blueprints.etf import etf_bp
    from blueprints.patrimonio import patrimonio_bp

    app.register_blueprint(home_bp)
    app.register_blueprint(input_bp)
    app.register_blueprint(elenco_bp)
    app.register_blueprint(bilancio_bp)
    app.register_blueprint(statistiche_bp)
    app.register_blueprint(etf_bp)
    app.register_blueprint(patrimonio_bp)

    return app


if __name__ == "__main__":
    app = create_app()
    app.run(debug=True)
