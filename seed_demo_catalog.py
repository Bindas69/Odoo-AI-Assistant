#!/usr/bin/env python3
"""
seed_demo_catalog.py

Seeds a small, realistic demo product catalog into Odoo for Project #2
(AI Inventory Assistant). Creates product categories, products (with
SKU/price), and sets on-hand stock quantities via stock.quant.

Uses standard Odoo external API auth (common.login + object.execute_kw
over JSON-RPC) — NOT the session-cookie hack from Project #1, which was
only required because PDF report rendering isn't exposed via JSON-RPC.
Plain CRUD like this works fine over the standard API.

Idempotent: re-running this script will skip products that already
exist (matched by default_code / SKU) rather than creating duplicates.

Usage:
    pip install requests --break-system-packages   # if not already installed
    export ODOO_URL=http://localhost:8069
    export ODOO_DB=odoo
    export ODOO_USERNAME=admin
    export ODOO_PASSWORD=admin
    python3 seed_demo_catalog.py
"""

import os
import sys
import requests

ODOO_URL = os.environ.get("ODOO_URL", "http://localhost:8069")
ODOO_DB = os.environ.get("ODOO_DB", "odoo")
ODOO_USERNAME = os.environ.get("ODOO_USERNAME", "admin")
ODOO_PASSWORD = os.environ.get("ODOO_PASSWORD", "admin")

JSONRPC_ENDPOINT = f"{ODOO_URL}/jsonrpc"

# --- Demo catalog -----------------------------------------------------
# 21 products across 3 categories, deliberately including:
#   - size/variant clusters (Blue T-Shirt S/M/L) for ambiguity-handling demos
#   - one zero-stock item (Red T-Shirt Medium) for out-of-stock demo
#   - a spread of prices for "under $X" category-filter demos (Phase 2)
CATEGORIES = ["Apparel", "Electronics", "Accessories"]

PRODUCTS = [
    # SKU,        Name,                       Category,      Price, Stock
    ("TS-BLU-S", "Blue T-Shirt Small",        "Apparel",     18.0, 23),
    ("TS-BLU-M", "Blue T-Shirt Medium",       "Apparel",     18.0, 11),
    ("TS-BLU-L", "Blue T-Shirt Large",        "Apparel",     18.0, 9),
    ("TS-RED-S", "Red T-Shirt Small",         "Apparel",     19.0, 14),
    ("TS-RED-M", "Red T-Shirt Medium",        "Apparel",     19.0, 0),
    ("TS-RED-L", "Red T-Shirt Large",         "Apparel",     19.0, 6),
    ("TS-BLK-M", "Black T-Shirt Medium",      "Apparel",     18.0, 20),
    ("HD-1TB",   "External Hard Drive 1TB",   "Electronics", 65.0, 8),
    ("HD-2TB",   "External Hard Drive 2TB",   "Electronics", 95.0, 5),
    ("MON-24",   "24\" Monitor",              "Electronics", 140.0, 4),
    ("MON-27",   "27\" Monitor",              "Electronics", 190.0, 3),
    ("CAM-HD",   "HD Webcam",                 "Electronics", 42.0, 6),
    ("SSD-512",  "SSD 512GB",                 "Electronics", 55.0, 19),
    ("SSD-1TB",  "SSD 1TB",                   "Electronics", 89.0, 12),
    ("KB-MECH",  "Mechanical Keyboard",       "Accessories", 75.0, 15),
    ("KB-WIRE",  "Wireless Keyboard",         "Accessories", 35.0, 22),
    ("MS-WIRE",  "Wireless Mouse",            "Accessories", 24.0, 31),
    ("MS-GAME",  "Gaming Mouse",              "Accessories", 39.0, 17),
    ("HP-USB",   "USB Headphones",            "Accessories", 28.0, 17),
    ("HP-BT",    "Bluetooth Headphones",      "Accessories", 58.0, 10),
    ("BAG-LAP",  "Laptop Bag",                "Accessories", 33.0, 13),
]
# -----------------------------------------------------------------------


def jsonrpc_call(service, method, args):
    payload = {
        "jsonrpc": "2.0",
        "method": "call",
        "params": {
            "service": service,
            "method": method,
            "args": args,
        },
        "id": 1,
    }
    resp = requests.post(JSONRPC_ENDPOINT, json=payload, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    if "error" in data:
        raise RuntimeError(f"Odoo RPC error: {data['error']}")
    return data["result"]


def authenticate():
    uid = jsonrpc_call(
        "common", "login", [ODOO_DB, ODOO_USERNAME, ODOO_PASSWORD]
    )
    if not uid:
        print("ERROR: Authentication failed. Check ODOO_DB / ODOO_USERNAME / ODOO_PASSWORD.")
        sys.exit(1)
    print(f"Authenticated as uid={uid}")
    return uid


def execute_kw(uid, model, method, args, kwargs=None):
    return jsonrpc_call(
        "object",
        "execute_kw",
        [ODOO_DB, uid, ODOO_PASSWORD, model, method, args, kwargs or {}],
    )


def get_or_create_category(uid, name):
    existing = execute_kw(
        uid, "product.category", "search", [[["name", "=", name]]]
    )
    if existing:
        return existing[0]
    cat_id = execute_kw(uid, "product.category", "create", [{"name": name}])
    print(f"  Created category: {name} (id={cat_id})")
    return cat_id


def get_internal_stock_location(uid):
    """Find the default internal stock location (usually 'WH/Stock')."""
    location_ids = execute_kw(
        uid,
        "stock.location",
        "search",
        [[["usage", "=", "internal"]]],
        {"limit": 1, "order": "id asc"},
    )
    if not location_ids:
        raise RuntimeError(
            "No internal stock location found. Is the Inventory app installed?"
        )
    return location_ids[0]


def get_or_create_product(uid, sku, name, category_id, price):
    existing = execute_kw(
        uid, "product.product", "search", [[["default_code", "=", sku]]]
    )
    if existing:
        print(f"  Skipping (already exists): {sku} - {name}")
        return existing[0], False

    product_id = execute_kw(
        uid,
        "product.product",
        "create",
        [
            {
                "name": name,
                "default_code": sku,
                "categ_id": category_id,
                "list_price": price,
                "type": "product",  # storable product, needed for stock tracking
            }
        ],
    )
    print(f"  Created product: {sku} - {name} (id={product_id})")
    return product_id, True


def set_stock_quantity(uid, product_id, location_id, quantity, sku):
    if quantity <= 0:
        # Leave at 0 (Odoo default for new products) — nothing to set.
        return

    existing_quant = execute_kw(
        uid,
        "stock.quant",
        "search",
        [[["product_id", "=", product_id], ["location_id", "=", location_id]]],
    )
    if existing_quant:
        print(f"    Stock already set for {sku}, skipping quantity update")
        return

    execute_kw(
        uid,
        "stock.quant",
        "create",
        [
            {
                "product_id": product_id,
                "location_id": location_id,
                "quantity": quantity,
            }
        ],
    )
    print(f"    Set stock: {sku} = {quantity} units")


def main():
    print(f"Connecting to Odoo at {ODOO_URL} (db={ODOO_DB})...")
    uid = authenticate()

    print("\nEnsuring categories exist...")
    category_ids = {name: get_or_create_category(uid, name) for name in CATEGORIES}

    print("\nFinding internal stock location...")
    location_id = get_internal_stock_location(uid)
    print(f"  Using location_id={location_id}")

    print(f"\nSeeding {len(PRODUCTS)} products...")
    created_count = 0
    for sku, name, category_name, price, stock in PRODUCTS:
        product_id, was_created = get_or_create_product(
            uid, sku, name, category_ids[category_name], price
        )
        if was_created:
            created_count += 1
        set_stock_quantity(uid, product_id, location_id, stock, sku)

    print(f"\nDone. {created_count} new products created, "
          f"{len(PRODUCTS) - created_count} already existed.")
    print("\nVerify in Odoo UI: Inventory → Products, or Sales → Products.")


if __name__ == "__main__":
    main()
