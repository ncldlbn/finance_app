import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

class Config:
    # Required in production (see create_app); no default so a known key can never sign sessions.
    SECRET_KEY = os.environ.get('SECRET_KEY', '')
    # FINANCE_DB can point to another SQLite file (e.g. the demo database).
    FINANCE_DB  = os.environ.get('FINANCE_DB', os.path.join(BASE_DIR, 'data', 'finance.db'))
    # Se impostata (postgresql://utente:password@host:5432/nome), l'app usa PostgreSQL invece di SQLite.
    DATABASE_URL = os.environ.get('DATABASE_URL', '')
    # PostgreSQL, proprietario del database: serve solo a chi applica le migrazioni (in docker compose il
    # servizio «migrate»); l'app usa DATABASE_URL, un utente senza privilegi soggetto alla Row-Level Security.
    DATABASE_OWNER_URL = os.environ.get('DATABASE_OWNER_URL', '')
    DEBUG = False

class DevelopmentConfig(Config):
    DEBUG = True

class ProductionConfig(Config):
    pass
