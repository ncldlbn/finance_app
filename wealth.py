"""Patrimonio a "posti" predefiniti.

Il patrimonio è organizzato in GRUPPI (i quattro pilastri più pensione, TFR, altri investimenti, crediti e
passività) e ogni gruppo ha un numero fisso di POSTI con un codice stabile (`liq_1`, `lungo_2`…). L'utente
non crea strutture: sceglie il NOME di ogni posto e se è VISIBILE (modulo, tabella, grafico), e per ogni
gruppo se CONTA NEL TOTALE. I valori stanno in `wealth_values` (una riga per posto e per mese): una riga
mancante significa "non inserito", che è diverso da zero.

Regole che non cambiano mai:
  - nascondere un posto NON toglie i suoi valori dai totali del gruppo (nessun importo sparisce in silenzio);
  - il totale = somma dei gruppi che contano, con segno negativo per le passività;
  - il totale si calcola al momento con la regola in vigore, quindi vale per tutta la storia.

Aggiungere un posto o un gruppo = una riga in GROUPS: niente modifiche allo schema.
"""
from collections import OrderedDict

# key, etichetta, colore (chiave in palette.PATRIMONIO), segno, conta nel totale di default, posti (codice, nome di default)
GROUPS = [
    dict(key='liq', label='Liquidità', color='liquidita', sign=1, counts=True,
         slots=[('liq_1', 'Conto corrente 1'), ('liq_2', 'Conto corrente 2'), ('liq_3', 'Conto corrente 3'), ('liq_4', 'Conto corrente 4')]),
    dict(key='emerg', label='Fondo emergenza', color='conto', sign=1, counts=True,
         slots=[('emerg_1', 'Fondo emergenza')]),
    dict(key='breve', label='Breve termine (obbligazionario)', color='obblig', sign=1, counts=True,
         slots=[('breve_1', 'Obbligazioni')]),
    dict(key='lungo', label='Lungo termine', color='etf', sign=1, counts=True,
         slots=[('lungo_1', 'Azioni'), ('lungo_2', 'ETF / ETC / ETN')]),
    dict(key='pens', label='Pensione complementare', color='previdenza', sign=1, counts=False,
         slots=[('pens_1', 'Pensione complementare 1'), ('pens_2', 'Pensione complementare 2')]),
    dict(key='tfr', label='TFR', color='tfr', sign=1, counts=False,
         slots=[('tfr_1', 'TFR')]),
    dict(key='altri', label='Altri investimenti', color='altri', sign=1, counts=False,
         slots=[('altri_1', 'Altri investimenti 1'), ('altri_2', 'Altri investimenti 2')]),
    dict(key='cred', label='Crediti e cauzioni', color='crediti', sign=1, counts=False,
         slots=[('cred_1', 'Credito 1'), ('cred_2', 'Credito 2')]),
    dict(key='pass', label='Passività', color='passivita', sign=-1, counts=False,
         slots=[('pass_1', 'Mutuo / prestito 1'), ('pass_2', 'Mutuo / prestito 2')]),
]
GROUP = {g['key']: g for g in GROUPS}
SLOT_GROUP = {code: g['key'] for g in GROUPS for code, _ in g['slots']}
SLOT_DEFAULT_LABEL = {code: label for g in GROUPS for code, label in g['slots']}
ALL_SLOTS = [code for g in GROUPS for code, _ in g['slots']]
# Visibili di default: il primo posto di ciascun pilastro (un nuovo utente non vede venti campi).
DEFAULT_VISIBLE = {'liq_1', 'emerg_1', 'breve_1', 'lungo_1'}
LABEL_MAX = 40

# Scelte rapide per "conta nel totale"
PRESETS = {
    'finanziario': {'liq', 'emerg', 'breve', 'lungo'},       # i quattro pilastri (il totale di sempre)
    'netto': {g['key'] for g in GROUPS},                      # tutto, con le passività sottratte
}
PRESET_LABELS = {'finanziario': 'Patrimonio finanziario', 'netto': 'Patrimonio netto'}


def config(conn):
    """Configurazione dell'utente corrente (nomi, visibilità, regola del totale) con i default dove manca."""
    custom = {r[0]: (r[1], bool(r[2])) for r in conn.execute(
        'SELECT slot, label, visible FROM wealth_slots WHERE user_id=current_uid()')}
    counts = {r[0]: bool(r[1]) for r in conn.execute(
        'SELECT grp, counts FROM wealth_group_settings WHERE user_id=current_uid()')}
    groups = []
    for g in GROUPS:
        slots = []
        for code, default in g['slots']:
            label, visible = custom.get(code, (default, code in DEFAULT_VISIBLE))
            slots.append(dict(code=code, group=g['key'], label=label or default, default_label=default, visible=visible))
        groups.append(dict(key=g['key'], label=g['label'], color=g['color'], sign=g['sign'],
                           counts=counts.get(g['key'], g['counts']), slots=slots,
                           shown=any(s['visible'] for s in slots)))
    return dict(groups=groups, slots={s['code']: s for gr in groups for s in gr['slots']},
                counts={gr['key']: gr['counts'] for gr in groups})


def months(conn):
    """Tutti i mesi con almeno un valore, dal più recente: [{anno, mese, values: {slot: importo}}]."""
    by = OrderedDict()
    for anno, mese, slot, value in conn.execute(
            'SELECT anno, mese, slot, value FROM wealth_values WHERE user_id=current_uid() ORDER BY anno DESC, mese DESC'):
        by.setdefault((anno, mese), {})[slot] = value
    return [dict(anno=a, mese=m, values=v) for (a, m), v in by.items()]


def group_sums(values):
    """Somma per gruppo (tutti i posti, anche quelli nascosti) per un mese."""
    return {g['key']: sum(values.get(code, 0.0) for code, _ in g['slots']) for g in GROUPS}


def total(sums, counts):
    """Totale secondo la regola: gruppi che contano, passività con segno negativo."""
    return sum(GROUP[k]['sign'] * v for k, v in sums.items() if counts.get(k))


def hidden_with_values(conn, cfg):
    """Posti nascosti che contengono valori: contano ancora nel totale, e l'utente va avvisato."""
    hidden = [c for c, s in cfg['slots'].items() if not s['visible']]
    if not hidden:
        return {}
    ph = ','.join('?' * len(hidden))
    return dict(conn.execute(
        f'SELECT slot, COUNT(*) FROM wealth_values WHERE user_id=current_uid() AND slot IN ({ph}) GROUP BY slot', hidden).fetchall())
