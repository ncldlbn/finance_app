"""Porta lo schema PostgreSQL all'ultima versione e crea/aggiorna l'utente dell'app.

    DATABASE_OWNER_URL=postgresql://proprietario:password@host/nome APP_DB_PASSWORD=... python scripts/migrate_pg.py

In docker compose lo esegue il servizio «migrate» prima che parta l'app. Si può rilanciare quando si vuole:
applica solo le migrazioni mancanti.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main():
    url = os.environ.get('DATABASE_OWNER_URL')
    if not url:
        sys.exit('Imposta DATABASE_OWNER_URL (postgresql://proprietario:password@host/nome).')
    import migrations
    import migrations_pg
    if migrations_pg.SQLITE_LEVEL != migrations.LATEST:
        sys.exit(f'Manca la migrazione PostgreSQL per la migrazione SQLite {migrations.LATEST} (migrations_pg.py).')
    password = os.environ.get('APP_DB_PASSWORD', '')
    version = migrations_pg.migrate(url, log=print, app_role=os.environ.get('APP_DB_USER', 'bilancio_app'),
                                    app_password=password)
    print(f'Schema PostgreSQL alla versione {version}.' + ('' if password else
          ' (APP_DB_PASSWORD non impostata: utente dell\'app non creato né aggiornato)'))


if __name__ == '__main__':
    main()
