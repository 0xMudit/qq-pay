"""Account-owned sandbox checkout links and atomic ledger transitions."""

import csv
import io
import time
import uuid
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field, StringConstraints
from typing import Annotated
from sqlalchemy import text

SCHEMA = """
CREATE TABLE IF NOT EXISTS beta_payments (id TEXT PRIMARY KEY, owner TEXT NOT NULL REFERENCES beta_users(id), idem TEXT NOT NULL, title TEXT NOT NULL, amount BIGINT NOT NULL CHECK(amount>0), currency TEXT NOT NULL, status TEXT NOT NULL, created DOUBLE PRECISION NOT NULL, UNIQUE(owner,idem));
CREATE INDEX IF NOT EXISTS beta_payments_owner ON beta_payments(owner,created);
CREATE TABLE IF NOT EXISTS beta_ledger (id TEXT PRIMARY KEY, payment TEXT NOT NULL REFERENCES beta_payments(id), account TEXT NOT NULL, amount BIGINT NOT NULL, currency TEXT NOT NULL, kind TEXT NOT NULL, created DOUBLE PRECISION NOT NULL);
CREATE INDEX IF NOT EXISTS beta_ledger_payment ON beta_ledger(payment);
CREATE TABLE IF NOT EXISTS beta_events (id TEXT PRIMARY KEY, payment TEXT NOT NULL REFERENCES beta_payments(id), kind TEXT NOT NULL, note TEXT NOT NULL, created DOUBLE PRECISION NOT NULL);
CREATE INDEX IF NOT EXISTS beta_events_payment ON beta_events(payment,created);
CREATE TABLE IF NOT EXISTS beta_checkout_expiry (payment TEXT PRIMARY KEY REFERENCES beta_payments(id), expires DOUBLE PRECISION NOT NULL);
CREATE TABLE IF NOT EXISTS beta_refunds (id TEXT PRIMARY KEY, payment TEXT NOT NULL REFERENCES beta_payments(id), idem TEXT NOT NULL, amount BIGINT NOT NULL CHECK(amount>0), requested_amount BIGINT, reason TEXT NOT NULL, created DOUBLE PRECISION NOT NULL, UNIQUE(payment,idem))
"""


class CreatePayment(BaseModel):
    title: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=160)
    ]
    amount: int = Field(strict=True, gt=0, le=100000000)
    currency: Literal["INR", "USD", "EUR"] = "INR"
    idempotency_key: str = Field(min_length=8, max_length=128)

    expires_in_minutes: int | None = Field(default=None, ge=1, le=43200)


class Refund(BaseModel):
    reason: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=3, max_length=200)
    ]
    amount: int | None = Field(default=None, strict=True, gt=0)
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=128)


def payment_view(row):
    payment = dict(row)
    if (
        payment["status"] == "pending"
        and payment.get("expires") is not None
        and payment["expires"] <= time.time()
    ):
        payment["status"] = "expired"
    payment.pop("owner", None)
    payment.pop("idem", None)
    return payment


PAYMENT_VIEW = """
SELECT p.*, x.expires,
    CASE WHEN p.status = 'refunded' THEN p.amount ELSE COALESCE(r.total, 0) END AS refunded_amount
FROM beta_payments p
LEFT JOIN beta_checkout_expiry x ON x.payment = p.id
LEFT JOIN (SELECT payment, SUM(amount) AS total FROM beta_refunds GROUP BY payment) r
    ON r.payment = p.id
"""


def csv_text(value):
    # Spreadsheet programs can execute a formula even in a quoted CSV field.
    return (
        "'" + value
        if value.lstrip().startswith(("=", "+", "-", "@"))
        or value.startswith(("\t", "\r", "\n"))
        else value
    )


class Product:
    def __init__(self, engine, accounts):
        self.engine = engine
        self.accounts = accounts
        self.router = APIRouter(prefix="/api", tags=["Sandbox payments"])
        self._routes()

    def initialize(self):
        with self.engine.begin() as db:
            for statement in SCHEMA.split(";"):
                if statement.strip():
                    db.execute(text(statement))

    def event(self, db, payment, kind, note=""):
        db.execute(
            text("INSERT INTO beta_events VALUES(:id,:payment,:kind,:note,:created)"),
            {
                "id": str(uuid.uuid4()),
                "payment": payment,
                "kind": kind,
                "note": note,
                "created": time.time(),
            },
        )

    def entries(self, db, payment, kind):
        sign = 1 if kind == "capture" else -1
        for account, amount in [
            ("sandbox_clearing", -payment["amount"] * sign),
            ("merchant_payable", payment["amount"] * sign),
        ]:
            db.execute(
                text(
                    "INSERT INTO beta_ledger VALUES(:id,:payment,:account,:amount,:currency,:kind,:created)"
                ),
                {
                    "id": str(uuid.uuid4()),
                    "payment": payment["id"],
                    "account": account,
                    "amount": amount,
                    "currency": payment["currency"],
                    "kind": kind,
                    "created": time.time(),
                },
            )

    def _routes(self):
        router = self.router
        current = self.accounts.user

        def owned_payments(owner):
            with self.engine.connect() as db:
                return [
                    payment_view(row)
                    for row in db.execute(
                        text(
                            PAYMENT_VIEW
                            + " WHERE p.owner=:owner ORDER BY p.created DESC,p.id DESC LIMIT 500"
                        ),
                        {"owner": owner},
                    ).mappings()
                ]

        @router.get("/payments")
        def payments(user=Depends(current)):
            return owned_payments(user["id"])

        @router.get("/reports/reconciliation")
        def reconciliation(user=Depends(current)):
            with self.engine.connect() as db:
                rows = db.execute(
                    text("""
                    SELECT l.currency,
                        SUM(CASE WHEN l.account='merchant_payable' AND l.kind='capture' THEN l.amount ELSE 0 END) AS captured,
                        SUM(CASE WHEN l.account='merchant_payable' AND l.kind='refund' THEN -l.amount ELSE 0 END) AS refunded,
                        SUM(CASE WHEN l.account='merchant_payable' THEN l.amount ELSE 0 END) AS net,
                        SUM(l.amount) AS ledger_balance,
                        COUNT(*) AS entries
                    FROM beta_ledger l JOIN beta_payments p ON p.id=l.payment
                    WHERE p.owner=:owner GROUP BY l.currency ORDER BY l.currency
                """),
                    {"owner": user["id"]},
                ).mappings()
                return [
                    {
                        key: int(value) if key != "currency" else value
                        for key, value in row.items()
                    }
                    for row in rows
                ]

        @router.get("/reports/payments.csv")
        def export(user=Depends(current)):
            stream = io.StringIO(newline="")
            writer = csv.writer(stream)
            writer.writerow(
                [
                    "id",
                    "title",
                    "currency",
                    "amount_minor",
                    "refunded_minor",
                    "status",
                    "created_epoch",
                    "expires_epoch",
                ]
            )
            for row in owned_payments(user["id"]):
                writer.writerow(
                    [
                        row["id"],
                        csv_text(row["title"]),
                        row["currency"],
                        row["amount"],
                        row["refunded_amount"],
                        row["status"],
                        row["created"],
                        row["expires"],
                    ]
                )
            return Response(
                stream.getvalue(),
                media_type="text/csv",
                headers={
                    "Content-Disposition": 'attachment; filename="qq-pay-transactions.csv"'
                },
            )

        @router.post("/payments", status_code=201)
        def create(body: CreatePayment, user=Depends(current)):
            identifier = str(uuid.uuid4())
            with self.engine.begin() as db:
                suffix = (
                    " FOR UPDATE" if self.engine.dialect.name == "postgresql" else ""
                )
                db.execute(
                    text("SELECT id FROM beta_users WHERE id=:owner" + suffix),
                    {"owner": user["id"]},
                )
                previous = (
                    db.execute(
                        text(PAYMENT_VIEW + " WHERE p.owner=:owner AND p.idem=:idem"),
                        {"owner": user["id"], "idem": body.idempotency_key},
                    )
                    .mappings()
                    .first()
                )
                if previous:
                    if any(
                        previous[key] != getattr(body, key)
                        for key in ("amount", "currency", "title")
                    ):
                        raise HTTPException(
                            409, "Idempotency key reused for a different checkout"
                        )
                    previous_minutes = (
                        round((previous["expires"] - previous["created"]) / 60)
                        if previous["expires"] is not None
                        else None
                    )
                    if previous_minutes != body.expires_in_minutes:
                        raise HTTPException(
                            409, "Idempotency key reused with a different expiry"
                        )
                    return payment_view(previous)
                if (
                    db.execute(
                        text("SELECT count(*) FROM beta_payments WHERE owner=:owner"),
                        {"owner": user["id"]},
                    ).scalar_one()
                    >= 500
                ):
                    raise HTTPException(409, "Beta workspace limit: 500 checkouts")
                params = {
                    "id": identifier,
                    "owner": user["id"],
                    "idem": body.idempotency_key,
                    "title": body.title,
                    "amount": body.amount,
                    "currency": body.currency,
                    "status": "pending",
                    "created": time.time(),
                }
                db.execute(
                    text(
                        "INSERT INTO beta_payments VALUES(:id,:owner,:idem,:title,:amount,:currency,:status,:created)"
                    ),
                    params,
                )
                self.event(db, identifier, "created")
                expires = None
                if body.expires_in_minutes is not None:
                    expires = params["created"] + body.expires_in_minutes * 60
                    db.execute(
                        text("INSERT INTO beta_checkout_expiry VALUES(:id,:expires)"),
                        {"id": identifier, "expires": expires},
                    )
                return payment_view(
                    {**params, "expires": expires, "refunded_amount": 0}
                )

        @router.get("/payments/{identifier}")
        def detail(identifier: str, user=Depends(current)):
            with self.engine.connect() as db:
                payment = (
                    db.execute(
                        text(PAYMENT_VIEW + " WHERE p.id=:id AND p.owner=:owner"),
                        {"id": identifier, "owner": user["id"]},
                    )
                    .mappings()
                    .first()
                )
                if not payment:
                    raise HTTPException(404, "Checkout not found")
                ledger = [
                    dict(r)
                    for r in db.execute(
                        text(
                            "SELECT * FROM beta_ledger WHERE payment=:id ORDER BY created"
                        ),
                        {"id": identifier},
                    ).mappings()
                ]
                events = [
                    dict(r)
                    for r in db.execute(
                        text(
                            "SELECT * FROM beta_events WHERE payment=:id ORDER BY created"
                        ),
                        {"id": identifier},
                    ).mappings()
                ]
                return {
                    "payment": payment_view(payment),
                    "ledger": ledger,
                    "events": events,
                }

        @router.post("/payments/{identifier}/refund")
        def refund(identifier: str, body: Refund, user=Depends(current)):
            if body.amount is not None and body.idempotency_key is None:
                raise HTTPException(
                    422, "An idempotency key is required for partial refunds"
                )
            key = (
                "request:" + body.idempotency_key
                if body.idempotency_key
                else "legacy-full"
            )
            with self.engine.begin() as db:
                # Serialize refunds and captures on the same payment, including on SQLite.
                payment = (
                    db.execute(
                        text(
                            "UPDATE beta_payments SET status=status WHERE id=:id AND owner=:owner RETURNING *"
                        ),
                        {"id": identifier, "owner": user["id"]},
                    )
                    .mappings()
                    .first()
                )
                if not payment:
                    raise HTTPException(409, "Only a captured checkout can be refunded")
                previous = (
                    db.execute(
                        text(
                            "SELECT * FROM beta_refunds WHERE payment=:id AND idem=:key"
                        ),
                        {"id": identifier, "key": key},
                    )
                    .mappings()
                    .first()
                )
                total = int(
                    db.execute(
                        text(
                            "SELECT COALESCE(SUM(amount),0) FROM beta_refunds WHERE payment=:id"
                        ),
                        {"id": identifier},
                    ).scalar_one()
                )
                if previous:
                    if body.idempotency_key and (
                        previous["reason"] != body.reason
                        or previous["requested_amount"] != body.amount
                    ):
                        raise HTTPException(
                            409, "Idempotency key reused for a different refund"
                        )
                    return {
                        "status": payment["status"],
                        "refunded_amount": total,
                        "refund_id": previous["id"],
                    }
                if payment["status"] == "refunded" and body.idempotency_key is None:
                    return {"status": "refunded", "refunded_amount": payment["amount"]}
                if payment["status"] != "captured":
                    raise HTTPException(409, "Only a captured checkout can be refunded")
                remaining = payment["amount"] - total
                amount = body.amount if body.amount is not None else remaining
                if not 0 < amount <= remaining:
                    raise HTTPException(
                        409, "Refund exceeds the remaining captured amount"
                    )
                refund_id = str(uuid.uuid4())
                db.execute(
                    text(
                        "INSERT INTO beta_refunds (id,payment,idem,amount,requested_amount,reason,created) VALUES(:id,:payment,:key,:amount,:requested_amount,:reason,:created)"
                    ),
                    {
                        "id": refund_id,
                        "payment": identifier,
                        "key": key,
                        "amount": amount,
                        "requested_amount": body.amount,
                        "reason": body.reason,
                        "created": time.time(),
                    },
                )
                self.entries(db, {**payment, "amount": amount}, "refund")
                status = "refunded" if amount == remaining else "captured"
                db.execute(
                    text("UPDATE beta_payments SET status=:status WHERE id=:id"),
                    {"status": status, "id": identifier},
                )
                self.event(
                    db,
                    identifier,
                    "refunded" if status == "refunded" else "partially_refunded",
                    f"{amount} {payment['currency']} minor units Â· {body.reason}",
                )
                return {
                    "status": status,
                    "refunded_amount": total + amount,
                    "refund_id": refund_id,
                }

        @router.post("/payments/{identifier}/cancel")
        def cancel(identifier: str, user=Depends(current)):
            with self.engine.begin() as db:
                changed = db.execute(
                    text(
                        "UPDATE beta_payments SET status='cancelled' WHERE id=:id AND owner=:owner AND status='pending'"
                    ),
                    {"id": identifier, "owner": user["id"]},
                ).rowcount
                if not changed:
                    raise HTTPException(409, "Only pending checkouts can be cancelled")
                self.event(db, identifier, "cancelled")
            return {"status": "cancelled"}

        @router.get("/checkout/{identifier}")
        def checkout(identifier: str):
            with self.engine.connect() as db:
                payment = (
                    db.execute(
                        text(
                            "SELECT p.id,p.title,p.amount,p.currency,p.status,x.expires,u.username AS merchant FROM beta_payments p JOIN beta_users u ON u.id=p.owner LEFT JOIN beta_checkout_expiry x ON x.payment=p.id WHERE p.id=:id"
                        ),
                        {"id": identifier},
                    )
                    .mappings()
                    .first()
                )
                if not payment:
                    raise HTTPException(404, "Checkout not found")
                return {**payment_view(payment), "mode": "sandbox"}

        @router.post("/checkout/{identifier}/pay")
        def pay(identifier: str):
            try:
                if str(uuid.UUID(identifier)) != identifier:
                    raise ValueError
            except ValueError:
                raise HTTPException(404, "Checkout not found")
            self.accounts.limit("public-checkout:" + identifier, 20)
            clock = (
                "EXTRACT(EPOCH FROM clock_timestamp())"
                if self.engine.dialect.name == "postgresql"
                else "(julianday('now') - 2440587.5) * 86400"
            )
            with self.engine.begin() as db:
                row = (
                    db.execute(
                        text(
                            "UPDATE beta_payments SET status='captured' WHERE id=:id AND status='pending' AND NOT EXISTS (SELECT 1 FROM beta_checkout_expiry WHERE payment=:id AND expires<="
                            + clock
                            + ") RETURNING *"
                        ),
                        {"id": identifier},
                    )
                    .mappings()
                    .first()
                )
                if row:
                    self.entries(db, row, "capture")
                    self.event(
                        db, identifier, "captured", "Sandbox payment; no money moved"
                    )
                existing = db.execute(
                    text("SELECT status FROM beta_payments WHERE id=:id"),
                    {"id": identifier},
                ).scalar_one_or_none()
                if not existing:
                    raise HTTPException(404, "Checkout not found")
                if existing != "captured":
                    raise HTTPException(409, "This checkout is no longer payable")
                return {"status": "captured", "mode": "sandbox"}
