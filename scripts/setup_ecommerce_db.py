"""Setup script for the DBZenith E-Commerce database schema and official dataset.

Reads DATABASE_URL from .env or takes a custom connection string.
Creates the tables:
  - regions (region_id, region_name, country)
  - customers (customer_id, first_name, last_name, email, phone, address, region_id, created_at)
  - products (product_id, product_name, category, price, stock_quantity, created_at)
  - orders (order_id, customer_id, product_id, region_id, order_date, quantity, amount, status, created_at)
"""

import os
import sys
from pathlib import Path
from urllib.parse import urlparse

# Resolve paths
ROOT_DIR = Path(__file__).resolve().parent.parent
SQL_FILE = ROOT_DIR / "database" / "schema_and_dataset.sql"
ENV_FILE = ROOT_DIR / ".env"

def load_env_database_url() -> str:
    """Reads DATABASE_URL from .env if present."""
    if ENV_FILE.exists():
        with open(ENV_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("DATABASE_URL="):
                    val = line.split("=", 1)[1].strip().strip('"').strip("'")
                    # Clean up SQLAlchemy psycopg dialect prefix if present
                    if val.startswith("postgresql+psycopg://"):
                        val = "postgresql://" + val[len("postgresql+psycopg://"):]
                    return val
    return "postgresql://postgres:postgres@localhost:5432/dbzenith"

def main():
    import psycopg

    db_url = sys.argv[1] if len(sys.argv) > 1 else load_env_database_url()
    print(f"Connecting to database: {db_url}")

    if not SQL_FILE.exists():
        print(f"Error: SQL file not found at {SQL_FILE}")
        sys.exit(1)

    with open(SQL_FILE, "r", encoding="utf-8") as f:
        sql_content = f.read()

    try:
        with psycopg.connect(db_url, autocommit=True) as conn:
            with conn.cursor() as cur:
                print("Executing schema and dataset population...")
                cur.execute(sql_content)
                print("Schema created and data inserted successfully!\n")

                # Verify row counts
                tables = ["regions", "products", "customers", "orders"]
                print("Verification:")
                for tbl in tables:
                    cur.execute(f"SELECT COUNT(*) FROM {tbl};")
                    count = cur.fetchone()[0]
                    print(f"  - {tbl}: {count} records")

    except Exception as exc:
        print(f"Database setup error: {exc}", file=sys.stderr)
        print("\nTip: If the database 'dbzenith' does not exist yet, connect to 'postgres' and run:")
        print("  CREATE DATABASE dbzenith;")
        sys.exit(1)

if __name__ == "__main__":
    main()
