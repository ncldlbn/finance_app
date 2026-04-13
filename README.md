# Finance Tracker — Flask

Versione Flask del progetto originale Streamlit.

## Struttura

```
bilancio_flask/
├── app.py                  # App Flask + registrazione blueprint
├── db.py                   # Connessioni SQLite
├── requirements.txt
├── data/
│   └── finance.db          # DB spese/entrate/categorie
├── portfolio.db            # DB portafoglio ETF
├── blueprints/
│   ├── home.py
│   ├── input.py            # Inserimento spese/entrate
│   ├── elenco.py           # Lista movimenti con filtri, modifica, elimina
│   ├── bilancio.py         # Riepilogo mensile, storico, confronto annuale
│   ├── statistiche.py      # Analisi per categoria/anno
│   └── etf.py              # Portafoglio ETF con Yahoo Finance
├── templates/
│   ├── base.html           # Layout dark sidebar
│   ├── home.html
│   ├── input.html
│   ├── elenco.html
│   ├── bilancio.html
│   ├── statistiche.html
│   └── etf.html
└── static/
    ├── css/style.css       # Design dark sidebar, Syne + DM Sans
    └── js/main.js          # Tab, expander, Plotly config
```

## Setup

```bash
# 1. Crea e attiva un virtualenv
python -m venv venv
source venv/bin/activate        # Linux/Mac
venv\Scripts\activate           # Windows

# 2. Installa le dipendenze
pip install -r requirements.txt

# 3. Avvia l'app
python app.py
```

L'app sarà disponibile su **http://127.0.0.1:5000**

## Note

- Il DB `data/finance.db` contiene già i dati dell'app Streamlit originale.
- Per un DB vuoto, esegui `setup/dbinit.py` dalla cartella originale.
- I prezzi ETF vengono scaricati in tempo reale da Yahoo Finance (yfinance).
- I grafici usano Plotly.js caricato da CDN.
