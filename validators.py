"""Lettura e validazione dei dati che arrivano dall'esterno (moduli e parametri dell'indirizzo).

Regola: i parametri dell'indirizzo (pagina, anno, filtri…) NON devono mai far fallire la pagina —
si correggono in silenzio (`int_arg`, `clamp`). I dati dei moduli, invece, si controllano e, se non
vanno bene, si solleva `ValidationError`: l'app la trasforma in un messaggio (toast) e riporta
l'utente al modulo, evidenziando il campo (vedi `app.py`).
"""
import math
import re
from datetime import datetime

from flask import request

YEAR_MIN, YEAR_MAX = 1990, 2100
AMOUNT_MAX = 1e9            # un miliardo di euro: oltre è quasi certamente un errore di battitura
TEXT_MAX = 300              # lunghezza massima di descrizioni e nomi


class ValidationError(ValueError):
    """Dato non valido. `field` è il nome del campo del modulo da evidenziare (se c'è)."""
    def __init__(self, message, field=None):
        super().__init__(message)
        self.message, self.field = message, field


def parse_amount(raw, field='euro', label='Importo', *, positive=False, allow_zero=True, max_value=AMOUNT_MAX):
    """Importo in euro da testo: accetta la virgola decimale e rifiuta nan/inf/valori enormi.
    positive=True: solo valori > 0 (o >= 0 con allow_zero). Altrimenti anche negativi (rimborsi)."""
    text = str(raw if raw is not None else '').replace(' ', '').replace('€', '').replace(',', '.')
    if text == '':
        raise ValidationError(f'{label}: campo obbligatorio.', field)
    try:
        value = float(text)
    except ValueError:
        raise ValidationError(f'{label} non valido.', field) from None
    if not math.isfinite(value) or abs(value) > max_value:
        raise ValidationError(f'{label} non valido.', field)
    if positive and (value < 0 or (value == 0 and not allow_zero)):
        raise ValidationError(f'{label} deve essere maggiore di zero.', field)
    if not positive and value == 0 and not allow_zero:
        raise ValidationError(f'{label} non può essere zero.', field)
    return round(value, 2)


def parse_date(raw, field='date', label='Data'):
    """Data ISO (YYYY-MM-DD) esistente nel calendario e in un intervallo ragionevole."""
    text = str(raw or '').strip()
    try:
        d = datetime.strptime(text, '%Y-%m-%d')
    except ValueError:
        raise ValidationError(f'{label} non valida.', field) from None
    if not YEAR_MIN <= d.year <= YEAR_MAX:
        raise ValidationError(f'{label} fuori intervallo ({YEAR_MIN}–{YEAR_MAX}).', field)
    return d.strftime('%Y-%m-%d')


def parse_int(raw, field, label, lo, hi):
    """Intero in [lo, hi]."""
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        raise ValidationError(f'{label} non valido.', field) from None
    if not lo <= value <= hi:
        raise ValidationError(f'{label} deve essere tra {lo} e {hi}.', field)
    return value


def parse_year_month(raw_year, raw_month):
    """(anno, mese) dai campi `anno` e `mese` di un modulo."""
    return (parse_int(raw_year, 'anno', 'Anno', YEAR_MIN, YEAR_MAX),
            parse_int(raw_month, 'mese', 'Mese', 1, 12))


_YM = re.compile(r'^(\d{4})-(0[1-9]|1[0-2])$')


def parse_ym(raw, field='month', label='Mese'):
    """'YYYY-MM' valido."""
    m = _YM.match(str(raw or ''))
    if not m or not YEAR_MIN <= int(m.group(1)) <= YEAR_MAX:
        raise ValidationError(f'{label} non valido.', field)
    return raw


def parse_text(raw, field='description', label='Testo', *, required=False, max_len=TEXT_MAX):
    """Testo ripulito dagli spazi e limitato in lunghezza."""
    text = str(raw or '').strip()
    if required and not text:
        raise ValidationError(f'{label}: campo obbligatorio.', field)
    if len(text) > max_len:
        raise ValidationError(f'{label} troppo lungo (massimo {max_len} caratteri).', field)
    return text


def parse_id(raw, field='id'):
    """Identificativo numerico positivo."""
    return parse_int(raw, field, 'Identificativo', 1, 2**31 - 1)


def clamp(value, lo, hi):
    return max(lo, min(hi, value))


def int_arg(name, default, lo=1, hi=10**6):
    """Parametro intero dell'indirizzo: se manca o non è un numero vale `default`; sempre in [lo, hi]."""
    try:
        return clamp(int(request.args.get(name, default)), lo, hi)
    except (TypeError, ValueError):
        return default


def year_arg(name, default):
    """Parametro anno dell'indirizzo, o `default` se assente o fuori intervallo."""
    try:
        y = int(request.args.get(name, ''))
    except (TypeError, ValueError):
        return default
    return y if YEAR_MIN <= y <= YEAR_MAX else default
