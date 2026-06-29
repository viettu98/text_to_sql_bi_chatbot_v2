# -*- coding: utf-8 -*-
"""
Init database: load 4 CSV files vào SQLite.
Chạy 1 lần để tạo database/sales.db
"""
import sqlite3
import pandas as pd
import os

DB_DIR = os.path.join(os.path.dirname(__file__), "database")
DB_PATH = os.path.join(DB_DIR, "sales.db")
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")

os.makedirs(DB_DIR, exist_ok=True)

conn = sqlite3.connect(DB_PATH)

customers  = pd.read_csv(os.path.join(DATA_DIR, "Customers_realistic.csv"))
products   = pd.read_csv(os.path.join(DATA_DIR, "Products_v2.csv"))
promotions = pd.read_csv(os.path.join(DATA_DIR, "Promotion.csv"))
sales      = pd.read_csv(os.path.join(DATA_DIR, "Sales_order_v4.csv"))

customers.to_sql("customers",    conn, if_exists="replace", index=False)
products.to_sql("products",      conn, if_exists="replace", index=False)
promotions.to_sql("promotions",  conn, if_exists="replace", index=False)
sales.to_sql("sales_orders",     conn, if_exists="replace", index=False)

conn.commit()

cursor = conn.cursor()
cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = cursor.fetchall()
conn.close()

print(f"DB created at: {DB_PATH}")
print(f"Tables: {[t[0] for t in tables]}")
print(f"  customers:   {len(customers):>6,} rows")
print(f"  products:    {len(products):>6,} rows")
print(f"  promotions:  {len(promotions):>6,} rows")
print(f"  sales_orders:{len(sales):>6,} rows")
