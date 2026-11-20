"""Migrazioni dello schema PostgreSQL.

Lo schema di partenza è schema_pg.sql (versione 0, uguale allo schema SQLite alla migrazione SQLITE_LEVEL);
qui sotto le modifiche successive, applicate in ordine una sola volta e registrate in `schema_migrations`.
Le esegue il PROPRIETARIO del database (DATABASE_OWNER_URL): l'app usa un utente senza privilegi, a cui si
applica la Row-Level Security, e non può cambiare lo schema.

Regola: ogni nuova migrazione SQLite (migrations.py) va portata anche qui, poi si aggiorna SQLITE_LEVEL. Se le
due versioni non coincidono l'app si ferma con un messaggio, invece di lavorare su uno schema sbagliato.
"""
import os

SQLITE_LEVEL = 7          # schema_pg.sql + le migrazioni qui sotto comprendono le migrazioni SQLite fino a questa
LOCK_ID = 727274          # pg_advisory_lock: più processi non applicano le migrazioni insieme

# Tabelle con dati personali (colonna user_id): chiave esterna verso users e Row-Level Security.
PERSONAL_TABLES = ('category', 'expenses', 'incomes', 'budgets', 'planned_expenses', 'recurring_expenses',
                   'wealth_slots', 'wealth_group_settings', 'wealth_values', 'patrimonio')

DATE_RE = r"'^[0-9]{4}-(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])$'"
MONTH_RE = r"'^[0-9]{4}-(0[1-9]|1[0-2])$'"

M1_TIPI = """
-- Date vere e importi esatti al centesimo. L'app riceve comunque le date come testo AAAA-MM-GG e gli
-- importi come numeri decimali normali (lo fa db.py), quindi il codice non cambia.
CREATE OR REPLACE FUNCTION strftime(fmt text, d date) RETURNS text LANGUAGE sql IMMUTABLE AS $$
    SELECT to_char(d, replace(replace(replace(fmt, '%Y', 'YYYY'), '%m', 'MM'), '%d', 'DD'))
$$;
ALTER TABLE expenses
    ALTER COLUMN date TYPE date USING date::date,
    ALTER COLUMN euro TYPE numeric(12,2) USING round(euro::numeric, 2);
ALTER TABLE incomes
    ALTER COLUMN date TYPE date USING date::date,
    ALTER COLUMN euro TYPE numeric(12,2) USING round(euro::numeric, 2);
ALTER TABLE planned_expenses   ALTER COLUMN euro  TYPE numeric(12,2) USING round(euro::numeric, 2);
ALTER TABLE recurring_expenses ALTER COLUMN euro  TYPE numeric(12,2) USING round(euro::numeric, 2);
ALTER TABLE budgets            ALTER COLUMN value TYPE numeric(12,2) USING round(value::numeric, 2);
ALTER TABLE category           ALTER COLUMN budget TYPE numeric(12,2) USING round(budget::numeric, 2);
ALTER TABLE wealth_values      ALTER COLUMN value TYPE numeric(14,2) USING round(value::numeric, 2);
ALTER TABLE patrimonio
    ALTER COLUMN bcc TYPE numeric(14,2), ALTER COLUMN bbva TYPE numeric(14,2), ALTER COLUMN directa TYPE numeric(14,2),
    ALTER COLUMN deposito TYPE numeric(14,2), ALTER COLUMN obblig TYPE numeric(14,2), ALTER COLUMN etf_etc TYPE numeric(14,2),
    ALTER COLUMN debito TYPE numeric(14,2), ALTER COLUMN credito TYPE numeric(14,2), ALTER COLUMN cauzioni TYPE numeric(14,2),
    ALTER COLUMN tfr TYPE numeric(14,2), ALTER COLUMN fon_te TYPE numeric(14,2);
ALTER TABLE users ALTER COLUMN created_at DROP DEFAULT;
ALTER TABLE users ALTER COLUMN created_at TYPE timestamptz
    USING (CASE WHEN created_at = '' THEN now() ELSE created_at::timestamp AT TIME ZONE 'UTC' END);
ALTER TABLE users ALTER COLUMN created_at SET DEFAULT now();
"""

M2_VINCOLI = f"""
-- Chiavi esterne: ogni riga personale appartiene a un utente esistente, ed eliminando l'utente spariscono
-- anche tutte le sue righe. Gli id usati senza un utente (vecchi database a utente unico) diventano utenti
-- senza password, che non possono accedere.
INSERT INTO users (id, username, password_hash)
SELECT DISTINCT t.user_id, 'utente-' || t.user_id, ''
FROM ({' UNION '.join(f'SELECT user_id FROM {t}' for t in PERSONAL_TABLES)}) t
WHERE NOT EXISTS (SELECT 1 FROM users u WHERE u.id = t.user_id);
SELECT setval(pg_get_serial_sequence('users', 'id'), COALESCE((SELECT MAX(id) FROM users), 0) + 1, false);
{''.join(f'''
ALTER TABLE {t} ADD CONSTRAINT {t}_user_fk FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE;''' for t in PERSONAL_TABLES)}

-- Valori ammessi (gli stessi che l'app controlla già nei moduli).
ALTER TABLE users
    ADD CONSTRAINT users_theme_ck   CHECK (theme IN ('auto', 'light', 'dark')),
    ADD CONSTRAINT users_is_demo_ck CHECK (is_demo IN (0, 1)),
    ADD CONSTRAINT users_data_date_ck CHECK (data_date = '' OR data_date ~ {DATE_RE});
ALTER TABLE expenses
    ADD CONSTRAINT expenses_euro_ck CHECK (euro <> 0),
    ADD CONSTRAINT expenses_type_ck CHECK (type IS NULL OR type IN ('essential', 'extra'));
ALTER TABLE incomes
    ADD CONSTRAINT incomes_euro_ck  CHECK (euro <> 0);
ALTER TABLE category
    ADD CONSTRAINT category_visible_ck CHECK (visible IN (0, 1)),
    ADD CONSTRAINT category_name_ck    CHECK (btrim(category) <> '');
ALTER TABLE budgets
    ADD CONSTRAINT budgets_kind_ck   CHECK (kind IN ('essential', 'extra', 'savings')),
    ADD CONSTRAINT budgets_period_ck CHECK (period IN ('mensile', 'annuale')),
    ADD CONSTRAINT budgets_value_ck  CHECK (value >= 0),
    ADD CONSTRAINT budgets_year_ck   CHECK (year BETWEEN 1990 AND 2100);
ALTER TABLE planned_expenses
    ADD CONSTRAINT planned_euro_ck  CHECK (euro > 0),
    ADD CONSTRAINT planned_month_ck CHECK (month ~ {MONTH_RE}),
    ADD CONSTRAINT planned_due_ck   CHECK (due_date = '' OR due_date ~ {DATE_RE});
ALTER TABLE recurring_expenses
    ADD CONSTRAINT recurring_day_ck    CHECK (day_of_month BETWEEN 1 AND 31),
    ADD CONSTRAINT recurring_euro_ck   CHECK (euro > 0),
    ADD CONSTRAINT recurring_type_ck   CHECK (type IN ('essential', 'extra')),
    ADD CONSTRAINT recurring_flags_ck  CHECK (auto_insert IN (0, 1) AND active IN (0, 1)),
    ADD CONSTRAINT recurring_end_ck    CHECK (end_date = '' OR end_date ~ {DATE_RE});
ALTER TABLE wealth_slots          ADD CONSTRAINT wealth_slots_visible_ck CHECK (visible IN (0, 1));
ALTER TABLE wealth_group_settings ADD CONSTRAINT wealth_groups_counts_ck CHECK (counts IN (0, 1));
ALTER TABLE wealth_values
    ADD CONSTRAINT wealth_values_month_ck CHECK (mese BETWEEN 1 AND 12),
    ADD CONSTRAINT wealth_values_year_ck  CHECK (anno BETWEEN 1990 AND 2100);
ALTER TABLE patrimonio ADD CONSTRAINT patrimonio_month_ck CHECK (mese BETWEEN 1 AND 12);
"""

M3_RLS = ''.join(f"""
-- {t}: ognuno vede e modifica solo le proprie righe, anche se una query dimentica il filtro.
ALTER TABLE {t} ENABLE ROW LEVEL SECURITY;
CREATE POLICY {t}_own ON {t} USING (user_id = current_uid()) WITH CHECK (user_id = current_uid());
""" for t in PERSONAL_TABLES)

MIGRATIONS = [
    (1, 'tipi: date e importi', M1_TIPI),
    (2, 'vincoli: chiavi esterne e valori ammessi', M2_VINCOLI),
    (3, 'row-level security sulle tabelle personali', M3_RLS),
]
LATEST = MIGRATIONS[-1][0]
SCHEMA_PG = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'schema_pg.sql')


def _grant_app_role(raw, role, password, log):
    """Crea (o aggiorna) l'utente dell'app: niente proprietà, niente superpoteri, niente BYPASSRLS; solo lettura
    e scrittura delle righe. Le policy di Row-Level Security valgono per lui."""
    from psycopg import sql
    exists = raw.execute('SELECT 1 FROM pg_roles WHERE rolname = %s', (role,)).fetchone()
    stmt = 'ALTER ROLE {} WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS PASSWORD {}' if exists else \
           'CREATE ROLE {} WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS PASSWORD {}'
    raw.execute(sql.SQL(stmt).format(sql.Identifier(role), sql.Literal(password)))
    r = sql.Identifier(role)
    for q in ('GRANT USAGE ON SCHEMA public TO {}',
              'GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {}',
              'REVOKE INSERT, UPDATE, DELETE ON schema_migrations FROM {}',
              'GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA public TO {}'):
        raw.execute(sql.SQL(q).format(r))
    if log and not exists:
        log(f'Utente del database «{role}» creato (senza privilegi, soggetto alla Row-Level Security)')


def migrate(owner_url, log=print, app_role=None, app_password=None):
    """Porta lo schema all'ultima versione (crea lo schema di partenza se il database è vuoto). Ritorna la
    versione. Con app_role/app_password crea o aggiorna anche l'utente dell'app e i suoi permessi."""
    import psycopg
    with psycopg.connect(owner_url) as raw:
        raw.execute('SELECT pg_advisory_lock(%s)', (LOCK_ID,))
        try:
            has = lambda t: raw.execute('SELECT to_regclass(%s)', (f'public.{t}',)).fetchone()[0] is not None
            if not has('schema_migrations'):
                if not has('users'):
                    with open(SCHEMA_PG, encoding='utf-8') as f:
                        raw.execute(f.read())
                    if log:
                        log('Schema PostgreSQL di partenza creato')
                raw.execute('DROP TABLE IF EXISTS schema_version')          # prima versione del branch, senza storia
                raw.execute('CREATE TABLE schema_migrations (version integer PRIMARY KEY, name text NOT NULL, '
                            'applied_at timestamptz NOT NULL DEFAULT now())')
                raw.execute("INSERT INTO schema_migrations (version, name) VALUES (0, 'schema di partenza')")
                raw.commit()
            current = raw.execute('SELECT MAX(version) FROM schema_migrations').fetchone()[0]
            for version, name, body in MIGRATIONS:
                if version <= current:
                    continue
                with raw.transaction():
                    raw.execute(body)
                    raw.execute('INSERT INTO schema_migrations (version, name) VALUES (%s, %s)', (version, name))
                current = version
                if log:
                    log(f'Migrazione PostgreSQL applicata: {version:03d} {name}')
            if app_role and app_password:
                _grant_app_role(raw, app_role, app_password, log)
            raw.commit()
            return current
        finally:
            raw.execute('SELECT pg_advisory_unlock(%s)', (LOCK_ID,))
            raw.commit()
