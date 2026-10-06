import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

class Config:
    # Required in production (see create_app); no default so a known key can never sign sessions.
    SECRET_KEY = os.environ.get('SECRET_KEY', '')
    # FINANCE_DB can point to another SQLite file (e.g. the demo database).
    FINANCE_DB  = os.environ.get('FINANCE_DB', os.path.join(BASE_DIR, 'data', 'finance.db'))
    PORTFOLIO_DB = os.path.join(BASE_DIR, 'data', 'portfolio.db')
    DEBUG = False

class DevelopmentConfig(Config):
    DEBUG = True

class ProductionConfig(Config):
    pass
