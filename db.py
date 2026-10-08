import sqlite3
from contextlib import contextmanager

from config import Config


def _request_user_id():
    """Id dell'utente della richiesta in corso (None fuori da una richiesta o se non ha fatto l'accesso)."""
    try:
        from flask import g, has_request_context
    except ImportError:                                      # pragma: no cover
        return None
    if has_request_context():
        user = getattr(g, 'user', None)
        return user['id'] if user else None
    return None


@contextmanager
def finance_db(user_id=None):
    """Connessione al database, chiusa sempre alla fine.

    Ambito utente: nelle interrogazioni SQL, `current_uid()` vale l'id dell'utente a cui appartiene la
    connessione: `user_id` esplicito, altrimenti quello della richiesta in corso. Ogni interrogazione sui
    dati personali DEVE filtrare con `user_id = current_uid()` (e ogni INSERT usare `current_uid()`).
    Se non c'è nessun utente (richiesta anonima, script senza `user_id`), `current_uid()` solleva un errore:
    l'accesso ai dati fallisce invece di mescolare quelli di utenti diversi.
    """
    uid = user_id if user_id is not None else _request_user_id()

    def current_uid():
        if uid is None:
            raise sqlite3.ProgrammingError('Nessun utente associato a questa connessione')
        return uid

    conn = sqlite3.connect(Config.FINANCE_DB)
    conn.create_function('current_uid', 0, current_uid)
    try:
        yield conn
    finally:
        conn.close()
