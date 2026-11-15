"""Importazione dello storico da file CSV/TXT: spese, entrate e patrimonio.

Regole comuni (le stesse mostrate all'utente in Impostazioni › Dati):
  - codifica UTF-8 (anche con BOM) o Windows-1252; separatore `;`, `,` oppure tabulazione (si riconosce da solo);
  - la PRIMA RIGA è l'intestazione, con i nomi delle colonne (maiuscole e ordine non contano);
  - tutto o niente: se anche una sola riga non è valida non si importa nulla e si elencano gli errori;
  - le righe già presenti (stessa data, importo e categoria; per le entrate stessa data, importo e descrizione;
    per il patrimonio stesso mese) si saltano, quindi si può ripetere l'importazione senza creare doppioni.

Qui non c'è nulla di Flask: le funzioni leggono, controllano e restituiscono righe pronte; è il blueprint a
scrivere sul database.
"""
import csv
import io
from datetime import datetime

from validators import ValidationError, parse_amount, parse_date, parse_int, parse_text, YEAR_MIN, YEAR_MAX

MAX_BYTES = 2 * 1024 * 1024        # 2 MB: un decennio di spese sono poche centinaia di KB
MAX_ROWS = 20000
MAX_ERRORS = 15                    # errori elencati all'utente (il resto si riassume)

# Nomi accettati per le colonne (minuscolo): il primo è quello "ufficiale".
SPESE_COLS = {'data': ('data', 'date'), 'categoria': ('categoria', 'category'),
              'importo': ('importo', 'euro', 'amount'), 'descrizione': ('descrizione', 'description')}
ENTRATE_COLS = {'data': ('data', 'date'), 'importo': ('importo', 'euro', 'amount'),
                'descrizione': ('descrizione', 'description')}

FORMATS = {
    'spese': {
        'title': 'Spese',
        'header': 'data;categoria;importo;descrizione',
        'example': '2025-03-14;Alimentari;42,50;Spesa settimanale\n14/03/2025;Trasporti;1.250,00;Revisione auto',
        'rules': ['data, categoria e importo sono obbligatorie; descrizione è facoltativa',
                  'la categoria deve esistere già (Impostazioni › Categorie), maiuscole escluse',
                  'puoi usare anche il file scaricato da Elenco › CSV (la colonna «Tipo» viene ignorata)'],
    },
    'entrate': {
        'title': 'Entrate',
        'header': 'data;descrizione;importo',
        'example': '2025-03-27;Stipendio marzo;1850,00\n27/04/2025;Stipendio aprile;1850,00',
        'rules': ['data e importo sono obbligatorie; descrizione è facoltativa',
                  'puoi usare anche il file scaricato da Elenco › CSV'],
    },
    'patrimonio': {
        'title': 'Patrimonio',
        'header': 'anno;mese;Conto corrente 1;Fondo emergenza;ETF / ETC / ETN',
        'example': '2025;1;5200,00;12000,00;8300,50\n2025;2;5100,00;12000,00;8650,00',
        'rules': ['anno e mese sono obbligatori; le altre colonne sono i tuoi conti, col nome che hanno in '
                  'Impostazioni › Patrimonio (o col nome predefinito, o col codice, es. liq_1)',
                  'una cella vuota vuol dire «non inserito» (diverso da zero)',
                  'i mesi già presenti non si toccano: per correggerli usa la pagina Patrimonio',
                  'puoi partire dal file scaricato qui sotto con «Scarica il patrimonio»'],
    },
}


# ── Lettura del file ─────────────────────────────────────────────────────────

def read_table(raw):
    """Byte del file → (intestazione in minuscolo, [(numero di riga, [celle])]). ValidationError se illeggibile."""
    if not raw:
        raise ValidationError('Il file è vuoto.', 'file')
    if len(raw) > MAX_BYTES:
        raise ValidationError(f'File troppo grande (massimo {MAX_BYTES // 1024 // 1024} MB).', 'file')
    if b'\x00' in raw:
        raise ValidationError('Non sembra un file di testo (CSV o TXT).', 'file')
    try:
        text = raw.decode('utf-8-sig')
    except UnicodeDecodeError:
        text = raw.decode('cp1252', errors='replace')

    lines = [ln for ln in text.splitlines() if ln.strip()]
    if len(lines) < 2:
        raise ValidationError('Il file deve avere almeno l\'intestazione e una riga di dati.', 'file')
    first = lines[0]
    delim = max((';', '\t', ','), key=first.count)
    if first.count(delim) == 0:
        raise ValidationError('Separatore non riconosciuto: usa «;», «,» oppure la tabulazione.', 'file')

    reader = csv.reader(io.StringIO('\n'.join(lines)), delimiter=delim)
    header = [c.strip().lower() for c in next(reader)]
    rows = [(i, [c.strip() for c in row]) for i, row in enumerate(reader, start=2)]
    if len(rows) > MAX_ROWS:
        raise ValidationError(f'Troppe righe (massimo {MAX_ROWS}).', 'file')
    return header, rows


def _index(header, aliases, required):
    """Mappa nome-ufficiale → posizione della colonna; ValidationError se manca una colonna obbligatoria."""
    out = {}
    for official, names in aliases.items():
        pos = next((header.index(n) for n in names if n in header), None)
        if pos is None and official in required:
            raise ValidationError(f'Manca la colonna «{official}» nell\'intestazione.', 'file')
        out[official] = pos
    return out


def _cell(row, pos):
    return row[pos] if pos is not None and pos < len(row) else ''


# ── Valori ───────────────────────────────────────────────────────────────────

_DATE_FORMATS = ('%Y-%m-%d', '%d/%m/%Y', '%d-%m-%Y', '%d.%m.%Y')


def flexible_date(raw):
    """Data ISO da AAAA-MM-GG, GG/MM/AAAA, GG-MM-AAAA o GG.MM.AAAA."""
    text = (raw or '').strip()
    for fmt in _DATE_FORMATS:
        try:
            parsed = datetime.strptime(text, fmt)
        except ValueError:
            continue
        return parse_date(parsed.strftime('%Y-%m-%d'))      # controlla anche l'intervallo degli anni
    raise ValidationError('Data non valida (usa AAAA-MM-GG o GG/MM/AAAA).')


def flexible_amount(raw, label='Importo', allow_zero=False):
    """Importo con virgola o punto decimale e, se presente, il separatore delle migliaia ("1.250,50", "1,250.50")."""
    text = str(raw or '').replace(' ', '').replace('€', '').replace(' ', '')
    if ',' in text and '.' in text:
        dec = ',' if text.rfind(',') > text.rfind('.') else '.'
        text = text.replace('.' if dec == ',' else ',', '')
        text = text.replace(',', '.')
    return parse_amount(text, 'euro', label, allow_zero=allow_zero)


def _unsafe_prefix(text):
    """L'esportazione CSV antepone un apice ai testi che iniziano con = + - @ (contro le formule di Excel):
    importando lo si toglie, così andata e ritorno restituiscono il testo originale."""
    return text[1:] if text[:1] == "'" and text[1:2] in ('=', '+', '-', '@') else text


# ── Spese ed entrate ─────────────────────────────────────────────────────────

def parse_expenses(header, rows, categories):
    """Righe di spese pronte da inserire: ([{date, euro, category, type, description}], [errori]).
    `categories`: {nome in minuscolo: (nome, tipo)} delle categorie dell'utente."""
    idx = _index(header, SPESE_COLS, required={'data', 'categoria', 'importo'})
    ok, errors = [], []
    for n, row in rows:
        try:
            cat = _cell(row, idx['categoria']).strip()
            if cat.lower() not in categories:
                raise ValidationError(f'categoria «{cat}» inesistente.' if cat else 'categoria mancante.')
            name, tipo = categories[cat.lower()]
            ok.append(dict(date=flexible_date(_cell(row, idx['data'])), euro=flexible_amount(_cell(row, idx['importo'])),
                           category=name, type=tipo,
                           description=parse_text(_unsafe_prefix(_cell(row, idx['descrizione'])))))
        except ValidationError as e:
            errors.append(f'Riga {n}: {e.message}')
    return ok, errors


def parse_incomes(header, rows):
    idx = _index(header, ENTRATE_COLS, required={'data', 'importo'})
    ok, errors = [], []
    for n, row in rows:
        try:
            ok.append(dict(date=flexible_date(_cell(row, idx['data'])), euro=flexible_amount(_cell(row, idx['importo'])),
                           description=parse_text(_unsafe_prefix(_cell(row, idx['descrizione'])))))
        except ValidationError as e:
            errors.append(f'Riga {n}: {e.message}')
    return ok, errors


# ── Patrimonio ───────────────────────────────────────────────────────────────

def slot_lookup(cfg):
    """Nome di colonna (minuscolo) → codice del posto: nome scelto dall'utente, nome predefinito o codice.
    Un nome che corrisponde a più posti è ambiguo e viene escluso (lo segnala `parse_wealth`)."""
    seen, ambiguous = {}, set()
    for code, s in cfg['slots'].items():
        for name in {s['label'].lower(), s['default_label'].lower(), code}:
            if name in seen and seen[name] != code:
                ambiguous.add(name)
            seen[name] = code
    return {k: v for k, v in seen.items() if k not in ambiguous}, ambiguous


def parse_wealth(header, rows, cfg):
    """Mesi di patrimonio pronti: ([{anno, mese, values: {posto: importo}}], [errori])."""
    for need in ('anno', 'mese'):
        if need not in header:
            raise ValidationError(f'Manca la colonna «{need}» nell\'intestazione.', 'file')
    lookup, ambiguous = slot_lookup(cfg)
    cols, problems = {}, []
    for pos, name in enumerate(header):
        if name in ('anno', 'mese', ''):
            continue
        if name in ambiguous:
            problems.append(f'la colonna «{name}» corrisponde a più conti: usa il codice (es. liq_1)')
        elif name not in lookup:
            problems.append(f'colonna «{name}» sconosciuta: non è né il nome di un tuo conto né un codice')
        elif lookup[name] in cols.values():
            problems.append(f'la colonna «{name}» ripete un conto già presente')
        else:
            cols[pos] = lookup[name]
    if problems:
        raise ValidationError('Intestazione non valida: ' + '; '.join(problems) + '.', 'file')
    if not cols:
        raise ValidationError('Nessuna colonna di conti nell\'intestazione.', 'file')

    pos_anno, pos_mese = header.index('anno'), header.index('mese')
    ok, errors, seen = [], [], set()
    for n, row in rows:
        try:
            anno = parse_int(_cell(row, pos_anno), 'anno', 'Anno', YEAR_MIN, YEAR_MAX)
            mese = parse_int(_cell(row, pos_mese), 'mese', 'Mese', 1, 12)
            if (anno, mese) in seen:
                raise ValidationError(f'il mese {mese}/{anno} compare due volte nel file.')
            values = {}
            for pos, code in cols.items():
                raw = _cell(row, pos)
                if raw != '':
                    values[code] = flexible_amount(raw, cfg['slots'][code]['label'], allow_zero=True)
            if not values:
                raise ValidationError('nessun importo in questa riga.')
            seen.add((anno, mese))
            ok.append(dict(anno=anno, mese=mese, values=values))
        except ValidationError as e:
            errors.append(f'Riga {n}: {e.message}')
    return ok, errors


def wealth_export(cfg, months):
    """Testo CSV (stesso formato dell'importazione) con i posti visibili o usati, dal mese più vecchio."""
    used = {code for m in months for code in m['values']}
    codes = [c for c, s in cfg['slots'].items() if s['visible'] or c in used]
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=';', lineterminator='\r\n')
    w.writerow(['anno', 'mese'] + [cfg['slots'][c]['label'] for c in codes])
    for m in sorted(months, key=lambda m: (m['anno'], m['mese'])):
        w.writerow([m['anno'], m['mese']] + [f"{m['values'][c]:.2f}".replace('.', ',') if c in m['values'] else '' for c in codes])
    return '﻿' + buf.getvalue()


def summarize(errors):
    """Elenco di errori da mostrare: i primi MAX_ERRORS più una riga di riepilogo."""
    shown = errors[:MAX_ERRORS]
    if len(errors) > MAX_ERRORS:
        shown.append(f'… e altri {len(errors) - MAX_ERRORS} errori.')
    return shown
