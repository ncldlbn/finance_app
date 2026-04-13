import csv
import sqlite3
import re
from datetime import datetime

CSV_FILE = "spese.csv"
DB_FILE = "data/finance.db"


def parse_euro(value: str) -> float:
    """Converte '€ 7,32' o '7,32' in float."""
    cleaned = re.sub(r"[€\s]", "", value).replace(",", ".")
    return float(cleaned)


def parse_date(value: str) -> str:
    """Converte 'DD/MM/YYYY' in 'YYYY-MM-DD'."""
    return datetime.strptime(value.strip(), "%d/%m/%Y").strftime("%Y-%m-%d")


def load_category_map(conn: sqlite3.Connection) -> dict[str, str]:
    """Restituisce {category_name_lower: type} dalla tabella category."""
    cur = conn.execute("SELECT category, type FROM category")
    return {row[0].lower(): row[1] for row in cur.fetchall()}


def main():
    conn = sqlite3.connect(DB_FILE)

    category_map = load_category_map(conn)

    rows = []
    with open(CSV_FILE, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader, start=1):
            category = row["CATEGORIA"].strip()
            expense_type = category_map.get(category.lower())
            if expense_type is None:
                print(f"  ATTENZIONE: categoria '{category}' non trovata in category table, type sarà NULL")

            rows.append({
                "id": i,
                "date": parse_date(row["DATA"]),
                "user_id": 1,
                "euro": parse_euro(row["SPLIT"]),
                "description": row["DESCRIZIONE"].strip(),
                "category": category,
                "type": expense_type,
            })

    print(f"Righe lette dal CSV: {len(rows)}")

    conn.execute("DROP TABLE IF EXISTS expenses")
    conn.execute("""
        CREATE TABLE expenses (
            id INTEGER PRIMARY KEY,
            date TEXT NOT NULL,
            user_id INTEGER NOT NULL,
            euro REAL NOT NULL,
            description TEXT,
            category TEXT,
            type TEXT
        )
    """)

    conn.executemany(
        "INSERT INTO expenses (id, date, user_id, euro, description, category, type) "
        "VALUES (:id, :date, :user_id, :euro, :description, :category, :type)",
        rows,
    )

    conn.commit()
    conn.close()
    print(f"Tabella expenses ricreata con {len(rows)} righe.")


if __name__ == "__main__":
    main()
