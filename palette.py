# ============================================================
#  FINANCE TRACKER — PALETTE COLORI
#  Fonte di verità unica per Python e JavaScript.
#
#  Basata su Tailwind CSS 400-shades: vivaci e leggibili su
#  sfondi scuri, armonizzate tra loro.
#
#  In Python:  from palette import P, INCOME, ESSENTIAL, ...
#  In JS:      window.PALETTE  (iniettato da base.html)
# ============================================================

# ── Semantica finanziaria ────────────────────────────────────────────
INCOME    = '#4ade80'   # green-400   — entrate
EXPENSE   = '#f87171'   # red-400     — uscite totali
ESSENTIAL = '#818cf8'   # indigo-400  — spese necessarie
EXTRA     = '#fb923c'   # orange-400  — spese extra
SAVINGS   = '#c084fc'   # purple-400  — risparmio

# ── Stato regole budget ──────────────────────────────────────────────
RULE_OK      = '#4ade80'   # = INCOME
RULE_WARNING = '#fbbf24'   # amber-400  — leggermente sforata
RULE_DANGER  = '#f87171'   # = EXPENSE

# ── Palette anni (statistiche → spese, ETF donut, ecc.) ─────────────
YEAR_PALETTE = [
    '#818cf8',  # 1 — indigo-400   (= ESSENTIAL)
    '#4ade80',  # 2 — green-400    (= INCOME)
    '#fb923c',  # 3 — orange-400   (= EXTRA)
    '#f472b6',  # 4 — pink-400
    '#22d3ee',  # 5 — cyan-400
    '#c084fc',  # 6 — purple-400   (= SAVINGS)
    '#fbbf24',  # 7 — amber-400
]

# ── Classi patrimoniali ──────────────────────────────────────────────
PATRIMONIO = {
    'liquidita':       '#60a5fa',              # blue-400   — liquidità
    'liquidita_fill':  'rgba(96,165,250,0.20)',
    'conto':           '#818cf8',              # = ESSENTIAL — depositi/obblig
    'conto_fill':      'rgba(129,140,248,0.22)',
    'etf':             '#4ade80',              # = INCOME    — ETF/lungo
    'etf_fill':        'rgba(74,222,128,0.20)',
    'previdenza':      '#fb923c',              # = EXTRA     — previdenza
    'previdenza_fill': 'rgba(251,146,60,0.18)',
    'totale':          '#818cf8',              # = ESSENTIAL — linea totale
    'totale_fill':     'rgba(129,140,248,0.07)',
}

# ── Sankey link (rgba semi-trasparenti) ──────────────────────────────
SANKEY = {
    'link_savings':   'rgba(192,132,252,0.35)',  # savings → risparmio
    'link_expense':   'rgba(248,113,113,0.30)',  # entrate → spese totali
    'link_essential': 'rgba(129,140,248,0.35)',  # spese → necessità
    'link_extra':     'rgba(251,146,60,0.35)',   # spese → extra
    'link_cat_ess':   'rgba(129,140,248,0.20)',  # necessità → categoria
    'link_cat_ext':   'rgba(251,146,60,0.22)',   # extra → categoria
    'node_cat':       '#2c3048',                 # nodi foglia (categorie)
}

# ── Varianti dim per grafici a barre/sparkline ───────────────────────
ESSENTIAL_DIM = 'rgba(129,140,248,0.30)'

# ── Colori base Plotly (layout comuni a tutti i grafici) ─────────────
PLOT = {
    'bg':           'rgba(0,0,0,0)',
    'grid':         '#2c3048',
    'text':         '#7880a0',
    'hover_bg':     '#1a1d28',
    'hover_text':   '#dde1f0',
    'hover_border': '#2c3048',
}

# ── Dizionario completo esposto a Jinja / JS ─────────────────────────
P = {
    'income':    INCOME,
    'expense':   EXPENSE,
    'essential': ESSENTIAL,
    'extra':     EXTRA,
    'savings':   SAVINGS,

    'rule_ok':      RULE_OK,
    'rule_warning': RULE_WARNING,
    'rule_danger':  RULE_DANGER,

    'years':       YEAR_PALETTE,
    'essential_dim': ESSENTIAL_DIM,

    'patrimonio': PATRIMONIO,
    'sankey':     SANKEY,
    'plot':       PLOT,
}
