import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'finance-tracker-secret-key')
    FINANCE_DB  = os.path.join(BASE_DIR, 'data', 'finance.db')
    PORTFOLIO_DB = os.path.join(BASE_DIR, 'data', 'portfolio.db')
    DEBUG = False

class DevelopmentConfig(Config):
    DEBUG = True

class ProductionConfig(Config):
    pass
