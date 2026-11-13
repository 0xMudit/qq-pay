"""Account-owned sandbox checkout links and atomic ledger transitions."""

import time
import uuid
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text

SCHEMA = """
CREATE TABLE IF NOT EXISTS beta_payments (id TEXT PRIMARY KEY, owner TEXT NOT NULL REFERENCES beta_users(id), idem TEXT NOT NULL, title TEXT NOT NULL, amount BIGINT NOT NULL CHECK(amount>0), currency TEXT NOT NULL, status TEXT NOT NULL, created DOUBLE PRECISION NOT NULL, UNIQUE(owner,idem));
CREATE INDEX IF NOT EXISTS beta_payments_owner ON beta_payments(owner,created);
CREATE TABLE IF NOT EXISTS beta_ledger (id TEXT PRIMARY KEY, payment TEXT NOT NULL REFERENCES beta_payments(id), account TEXT NOT NULL, amount BIGINT NOT NULL, currency TEXT NOT NULL, kind TEXT NOT NULL, created DOUBLE PRECISION NOT NULL);
CREATE INDEX IF NOT EXISTS beta_ledger_payment ON beta_ledger(payment);
CREATE TABLE IF NOT EXISTS beta_events (id TEXT PRIMARY KEY, payment TEXT NOT NULL REFERENCES beta_payments(id), kind TEXT NOT NULL, note TEXT NOT NULL, created DOUBLE PRECISION NOT NULL)
"""


class CreatePayment(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    amount: int = Field(strict=True, gt=0, le=100000000)
    currency: Literal["INR", "USD", "EUR"] = "INR"
    idempotency_key: str = Field(min_length=8, max_length=128)


class Refund(BaseModel):
    reason: str = Field(min_length=3, max_length=200)


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

        @router.get("/payments")
        def payments(user=Depends(current)):
            with self.engine.connect() as db:
                return [
                    dict(r)
                    for r in db.execute(
                        text(
                            "SELECT id,title,amount,currency,status,created FROM beta_payments WHERE owner=:owner ORDER BY created DESC LIMIT 500"
                        ),
                        {"owner": user["id"]},
                    ).mappings()
                ]

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
                        text(
                            "SELECT * FROM beta_payments WHERE owner=:owner AND idem=:idem"
                        ),
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
                    return dict(previous)
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
                return params

        @router.get("/payments/{identifier}")
        def detail(identifier: str, user=Depends(current)):
            with self.engine.connect() as db:
                payment = (
                    db.execute(
                        text(
                            "SELECT * FROM beta_payments WHERE id=:id AND owner=:owner"
                        ),
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
                return {"payment": dict(payment), "ledger": ledger, "events": events}

        @router.post("/payments/{identifier}/refund")
        def refund(identifier: str, body: Refund, user=Depends(current)):
            with self.engine.begin() as db:
                row = (
                    db.execute(
                        text(
                            "UPDATE beta_payments SET status='refunded' WHERE id=:id AND owner=:owner AND status='captured' RETURNING *"
                        ),
                        {"id": identifier, "owner": user["id"]},
                    )
                    .mappings()
                    .first()
                )
                if row:
                    self.entries(db, row, "refund")
                    self.event(db, identifier, "refunded", body.reason)
                    return {"status": "refunded"}
                existing = db.execute(
                    text(
                        "SELECT status FROM beta_payments WHERE id=:id AND owner=:owner"
                    ),
                    {"id": identifier, "owner": user["id"]},
                ).scalar_one_or_none()
                if existing == "refunded":
                    return {"status": "refunded"}
                raise HTTPException(409, "Only a captured checkout can be refunded")

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
                            "SELECT p.id,p.title,p.amount,p.currency,p.status,u.username AS merchant FROM beta_payments p JOIN beta_users u ON u.id=p.owner WHERE p.id=:id"
                        ),
                        {"id": identifier},
                    )
                    .mappings()
                    .first()
                )
                if not payment:
                    raise HTTPException(404, "Checkout not found")
                return {**dict(payment), "mode": "sandbox"}

        @router.post("/checkout/{identifier}/pay")
        def pay(identifier: str):
            self.accounts.limit("public-checkout:" + identifier, 20)
            with self.engine.begin() as db:
                row = (
                    db.execute(
                        text(
                            "UPDATE beta_payments SET status='captured' WHERE id=:id AND status='pending' RETURNING *"
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
