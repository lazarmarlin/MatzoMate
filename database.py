import sqlite3
import json

con = sqlite3.connect("database.db")
cur = con.cursor()

cur.execute("""
CREATE TABLE IF NOT EXISTS products (
    barcode TEXT PRIMARY KEY,
    product_name TEXT,
    ingredients TEXT,
    href TEXT
)
""")
con.commit()


def findProduct(barcode):
    barcode = str(barcode)
    cur.execute("SELECT * FROM products WHERE barcode=?", (barcode,))
    row = cur.fetchone()

    if row:
        product = {
            "barcode": row[0],
            "product_name": row[1],
            "ingredients": json.loads(row[2]),
            "href": row[3]
        }
        print("Product found in database")
        return product

    print("Product not found in database")
    return None


def addProduct(barcode, product_name, ingredients, href):
    barcode = str(barcode)
    ingredients_json = json.dumps(ingredients)

    cur.execute(
        "INSERT OR REPLACE INTO products VALUES (?, ?, ?, ?)",
        (barcode, product_name, ingredients_json, href)
    )
    con.commit()
    print(f"Product added to database: {barcode}")  