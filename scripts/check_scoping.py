"""Controllo statico dell'isolamento tra utenti.

    python scripts/check_scoping.py

Cerca nel codice dell'app (blueprints/ e helpers.py) ogni istruzione SQL che legge o scrive una tabella con
dati personali e NON contiene il filtro per utente (`current_uid()` o `user_id`). Un filtro dimenticato
significherebbe che un utente vede o modifica i dati di un altro. Esce con codice 1 se ne trova.

Non sostituisce la prova a due utenti di `smoke.py` (che verifica il comportamento vero): la affianca, perché
un'istruzione scritta male in un ramo poco usato potrebbe sfuggire a una prova.
"""
import ast
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PERSONAL = ('expenses', 'incomes', 'category', 'patrimonio', 'recurring_expenses', 'planned_expenses', 'budgets')
TABLES = '|'.join(PERSONAL)
STATEMENT = re.compile(rf'\b(FROM|JOIN|INTO|UPDATE)\s+({TABLES})\b', re.I)
SCOPED = re.compile(r'current_uid\(\)|user_id', re.I)
# File in cui i dati si toccano senza utente per scelta (schema, utenti, demo, importazioni, script)
SKIP = {'auth.py'}


def sql_strings(tree):
    """(riga, testo) di ogni stringa del codice. Le f-string si valutano per intero (parti letterali unite):
    i loro frammenti non si guardano da soli, altrimenti 'UPDATE t SET' e 'WHERE user_id=…' sembrerebbero
    istruzioni separate."""
    inside = {id(v) for n in ast.walk(tree) if isinstance(n, ast.JoinedStr) for v in n.values}
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in inside:
            yield node.lineno, node.value
        elif isinstance(node, ast.JoinedStr):
            yield node.lineno, ''.join(v.value for v in node.values if isinstance(v, ast.Constant) and isinstance(v.value, str))


def main():
    files = [os.path.join(ROOT, 'helpers.py')]
    bp = os.path.join(ROOT, 'blueprints')
    files += [os.path.join(bp, f) for f in sorted(os.listdir(bp)) if f.endswith('.py') and f not in SKIP]
    problems = 0
    for path in files:
        tree = ast.parse(open(path, encoding='utf-8').read())
        seen = set()
        for line, text in sql_strings(tree):
            if (line, text) in seen or not STATEMENT.search(text):
                continue
            seen.add((line, text))
            if not SCOPED.search(text):
                problems += 1
                snippet = ' '.join(text.split())[:110]
                print(f'{os.path.relpath(path, ROOT)}:{line}: senza filtro per utente: {snippet}')
    print('Nessuna interrogazione senza filtro per utente.' if not problems else f'\n{problems} interrogazioni da correggere.')
    return 1 if problems else 0


if __name__ == '__main__':
    sys.exit(main())
