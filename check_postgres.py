"""Opt-in PostgreSQL concurrency check. Uses DATABASE_URL and synthetic records."""

import os, uuid
from concurrent.futures import ThreadPoolExecutor

assert os.environ.get("DATABASE_URL", "").startswith(
    "postgresql"
), "Requires PostgreSQL"
import app

key = "concurrency-" + str(uuid.uuid4())
with ThreadPoolExecutor(max_workers=8) as pool:
    payments = list(
        pool.map(
            lambda _: app.create_payment(app.Payment(amount=100, currency="INR"), key),
            range(8),
        )
    )
assert len({p["id"] for p in payments}) == 1
identifier = payments[0]["id"]
with ThreadPoolExecutor(max_workers=8) as pool:
    list(pool.map(lambda _: app.capture(identifier), range(8)))
entries = app.ledger(identifier)
assert len(entries) == 2 and sum(e["amount"] for e in entries) == 0
print("PASS: concurrent create/capture retained one payment and two balanced entries")
