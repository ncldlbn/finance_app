# ============================================================
#  FINANCE TRACKER — PALETTE
#  Fonte di verità unica per Python, Jinja e JavaScript.
#
#  In Python:  from palette import P, INCOME, ESSENTIAL, ...
#  In JS:      window.PALETTE  (iniettato da base.html)
#
#  ─ Come sono stati scelti questi colori ────────────────────
#  Non a occhio: ogni colore delle serie passa i controlli
#  automatici (banda di luminosità OKLCH, soglia di croma,
#  separazione sotto daltonismo, contrasto sulla superficie).
#  I valori sono tarati sulla superficie scura SURFACE.
#
#  Per riverificare dopo una modifica:
#    node scripts/validate_palette.js \
#      "#299388,#c45050,#2c59a2,#8456c1" \
#      --mode dark --surface "#15161a" --pairs all
#
#  Vincolo emerso dalla validazione: cinque tinte pairwise
#  distinguibili non esistono dentro la banda del tema scuro.
#  Per questo il RISPARMIO non è una quinta tinta di barra ma
#  viene disegnato come LINEA: la forma lo distingue sotto
#  qualsiasi tipo di daltonismo, senza rubare un colore.
# ============================================================

# ── Superfici e inchiostri ───────────────────────────────────────────
#  Neutro freddo quasi-nero: le superfici si distinguono per
#  luminosità, i bordi sono capelli di bianco a bassa opacità.
PAGE_BG    = '#0e0f13'   # piano pagina
SURFACE    = '#15161a'   # superficie card/grafico ← usata per validare
SURFACE_2  = '#1c1e24'   # superficie sollevata (hover, input)
SURFACE_3  = '#23262d'   # tracce/binari (es. anello vuoto del Ritmo)

INK        = '#f2f3f5'   # testo primario      16.3:1 su SURFACE
INK_SOFT   = '#a8adb8'   # testo secondario     8.0:1
INK_MUTED  = '#7f8593'   # etichette, assi      4.6:1
INK_FAINT  = '#565c68'   # testo tenue, zeri    2.7:1 (mai portante)

GRID       = '#262931'   # griglia: capello, solido, arretrato
BORDER     = 'rgba(255,255,255,0.07)'
BORDER_2   = 'rgba(255,255,255,0.13)'

# ── Serie finanziarie ────────────────────────────────────────────────
#  Ordine = ordine di legenda. Le prime quattro sono barre e passano
#  TUTTE le coppie (i toggle dello storico possono lasciarne accese
#  due qualsiasi): CVD ΔE 8.9, visione normale ΔE 15.6.
INCOME    = '#299388'   # entrate    — teal (unico verde del sistema)
EXPENSE   = '#c45050'   # uscite / valori negativi — rosso (unico rosso del sistema)
ESSENTIAL = '#2c59a2'   # necessità  — blu
EXTRA     = '#8456c1'   # extra      — viola
EXTRA_DIM = '#a98cd8'   # extra, tinta più chiara — per distinguere un
                        # aggregato (EXTRA pieno) dalle sue componenti
                        # (EXTRA_DIM) quando condividono lo stesso grafico,
                        # senza inventare una seconda tinta categorica
SAVINGS   = '#c2913f'   # risparmio  — oro/bronzo, tinta propria (non più verde)

# ── Stato: regola 50/30/20 ───────────────────────────────────────────
#  Scala riservata e fissa: non segue mai il tema e non deve mai
#  impersonare una serie. Va sempre accompagnata da testo/valore,
#  mai lasciata sola a portare il significato.
RULE_OK      = '#0ca30c'   # 5.4:1 su SURFACE
RULE_WARNING = '#fab219'   # 9.9:1
RULE_DANGER  = '#d03b3b'   # 3.8:1

# ── Palette anni (categorica) ────────────────────────────────────────
#  Ordine documentato e validato: l'ordine È il meccanismo di
#  sicurezza sul daltonismo, non una scelta estetica — le rotazioni
#  provate falliscono. Non riordinare senza rieseguire il validatore.
#  Coppie adiacenti: CVD ΔE 8.4, visione normale ΔE 19.3.
YEAR_PALETTE = [
    '#3987e5',  # 1 blu
    '#d95926',  # 2 arancio
    '#199e70',  # 3 acqua
    '#c98500',  # 4 giallo
    '#d55181',  # 5 magenta
    '#008300',  # 6 verde
    '#9085e9',  # 7 viola
    '#e66767',  # 8 rosso
]

# ── Classi patrimoniali ──────────────────────────────────────────────
PATRIMONIO = {
    'liquidita':       '#3987e5',
    'liquidita_fill':  'rgba(57,135,229,0.18)',
    'conto':           '#199e70',
    'conto_fill':      'rgba(25,158,112,0.18)',
    'etf':             '#39a564',
    'etf_fill':        'rgba(57,165,100,0.18)',
    'previdenza':      '#d9730d',
    'previdenza_fill': 'rgba(217,115,13,0.16)',
    'totale':          '#9085e9',
    'totale_fill':     'rgba(144,133,233,0.10)',
}

# ── Sankey ───────────────────────────────────────────────────────────
#  Tre sole classi cromatiche portano significato (risparmio,
#  necessità, extra): nel Sankey qualsiasi nodo può finire accanto a
#  qualsiasi altro, e su tutte le coppie più di tre tinte non si
#  distinguono. I nodi di passaggio e le foglie restano neutri.
SANKEY = {
    'node_neutral':   '#3a3f4b',                 # entrate, spese totali
    'node_cat':       '#272a33',                 # foglie categoria
    'node_savings':   SAVINGS,                    # "denaro che resta": tinta
                                                 # propria del risparmio (oro),
                                                 # distinta dai nodi neutri.
    'link_savings':   'rgba(194,145,63,0.32)',    # oro (SAVINGS)
    'link_expense':   'rgba(196,80,80,0.26)',     # rosso (EXPENSE)
    'link_essential': 'rgba(44,89,162,0.32)',     # blu (ESSENTIAL)
    'link_extra':     'rgba(132,86,193,0.32)',    # viola (EXTRA)
    'link_cat_ess':   'rgba(44,89,162,0.16)',
    'link_cat_ext':   'rgba(132,86,193,0.16)',
}

# ── Varianti smorzate ────────────────────────────────────────────────
ESSENTIAL_DIM = 'rgba(44,89,162,0.28)'

# ── Layout comune dei grafici Plotly ─────────────────────────────────
PLOT = {
    'bg':           'rgba(0,0,0,0)',
    'grid':         GRID,
    'text':         INK_MUTED,
    'surface':      SURFACE,      # per i distacchi fra marche
    'surface3':     SURFACE_3,    # tracce/binari
    'hover_bg':     '#1c1e24',
    'hover_text':   INK,
    'hover_border': 'rgba(255,255,255,0.13)',
}

# ── Dizionario completo esposto a Jinja / JS ─────────────────────────
P = {
    'income':    INCOME,
    'expense':   EXPENSE,
    'essential': ESSENTIAL,
    'extra':     EXTRA,
    'extra_dim': EXTRA_DIM,
    'savings':   SAVINGS,

    'rule_ok':      RULE_OK,
    'rule_warning': RULE_WARNING,
    'rule_danger':  RULE_DANGER,

    'years':         YEAR_PALETTE,
    'essential_dim': ESSENTIAL_DIM,

    'ink':       INK,
    'ink_soft':  INK_SOFT,
    'ink_muted': INK_MUTED,
    'ink_faint': INK_FAINT,
    'surface':   SURFACE,

    'patrimonio': PATRIMONIO,
    'sankey':     SANKEY,
    'plot':       PLOT,
}
