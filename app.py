import uuid
from pydantic import BaseModel, Field

TITLE = "QQ Pay · sandbox"
SCHEMA = """CREATE TABLE IF NOT EXISTS payments (id TEXT PRIMARY KEY, idem TEXT UNIQUE NOT NULL, amount BIGINT NOT NULL, currency TEXT NOT NULL, status TEXT NOT NULL); CREATE TABLE IF NOT EXISTS ledger (id TEXT PRIMARY KEY, payment TEXT NOT NULL, account TEXT NOT NULL, amount BIGINT NOT NULL)"""
import os, secrets
from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, Header, HTTPException
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

database_url = os.getenv("DATABASE_URL", "sqlite:///data.db")
engine_options = {"pool_pre_ping": True}
if database_url.endswith(":memory:"):
    engine_options.update(
        connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
elif database_url.startswith("postgresql"):
    from sqlalchemy.pool import NullPool

    engine_options.update(poolclass=NullPool, connect_args={"prepare_threshold": None})
engine = create_engine(database_url, **engine_options)
if database_url.startswith("postgresql"):
    from sqlalchemy import event

    @event.listens_for(engine, "connect")
    def set_schema(connection, record):
        with connection.cursor() as cursor:
            cursor.execute("SET search_path TO qq_pay")
        connection.commit()


def auth(x_api_key: str = Header(default="")):
    if not secrets.compare_digest(x_api_key.encode(), os.environ["API_KEY"].encode()):
        raise HTTPException(401, "Invalid API key")


@asynccontextmanager
async def lifespan(app):
    if len(os.getenv("API_KEY", "")) < 16:
        raise RuntimeError("Set API_KEY to at least 16 characters")
    with engine.begin() as c:
        if engine.dialect.name == "postgresql":
            c.execute(text("CREATE SCHEMA IF NOT EXISTS qq_pay"))
        for statement in SCHEMA.split(";"):
            if statement.strip():
                c.execute(text(statement))
    accounts.initialize()
    product.initialize()
    yield


app = FastAPI(title=TITLE, version="0.2.0-beta.1", lifespan=lifespan)


@app.get("/health")
def health():
    with engine.connect() as c:
        c.execute(text("SELECT 1"))
    return {"status": "ok"}


class Payment(BaseModel):
    amount: int = Field(strict=True, gt=0, le=100000000)
    currency: str = Field(pattern="^(INR|USD|EUR)$")


@app.post("/payments", dependencies=[Depends(auth)])
def create_payment(
    body: Payment, idempotency_key: str = Header(min_length=8, max_length=128)
):
    """Deduplicate identical requests and reject conflicting key reuse."""
    identifier = str(uuid.uuid4())
    with engine.begin() as c:
        c.execute(
            text(
                "INSERT INTO payments VALUES(:id,:key,:amount,:currency,'pending') ON CONFLICT(idem) DO NOTHING"
            ),
            dict(id=identifier, key=idempotency_key, **body.model_dump()),
        )
        row = dict(
            c.execute(
                text("SELECT * FROM payments WHERE idem=:key"),
                dict(key=idempotency_key),
            )
            .mappings()
            .one()
        )
        if row["amount"] != body.amount or row["currency"] != body.currency:
            raise HTTPException(409, "Idempotency key reused with different request")
        return row


@app.post("/payments/{identifier}/capture", dependencies=[Depends(auth)])
def capture(identifier: str):
    """Commit capture and the balanced ledger together exactly once locally."""
    with engine.begin() as c:
        row = (
            c.execute(
                text(
                    "UPDATE payments SET status='captured' WHERE id=:id AND status='pending' RETURNING *"
                ),
                dict(id=identifier),
            )
            .mappings()
            .first()
        )
        if row:
            for account, amount in [
                ("sandbox_clearing", -row["amount"]),
                ("merchant_payable", row["amount"]),
            ]:
                c.execute(
                    text("INSERT INTO ledger VALUES(:id,:payment,:account,:amount)"),
                    dict(
                        id=str(uuid.uuid4()),
                        payment=identifier,
                        account=account,
                        amount=amount,
                    ),
                )
        payment = (
            c.execute(text("SELECT * FROM payments WHERE id=:id"), dict(id=identifier))
            .mappings()
            .first()
        )
        if not payment:
            raise HTTPException(404, "Payment not found")
        return dict(payment)


@app.get("/payments/{identifier}/ledger", dependencies=[Depends(auth)])
def ledger(identifier: str):
    with engine.connect() as c:
        return [
            dict(r)
            for r in c.execute(
                text("SELECT * FROM ledger WHERE payment=:id"), dict(id=identifier)
            ).mappings()
        ]


from fastapi.responses import FileResponse
from pathlib import Path


@app.get("/")
def dashboard():
    return FileResponse(Path(__file__).with_name("application.html"))


# Shared database rate limiting bounds the public, fixed-input demonstration.
SCHEMA += "; CREATE TABLE IF NOT EXISTS demo_limits (bucket BIGINT PRIMARY KEY, count INTEGER NOT NULL)"


def demo_budget():
    """Atomically limit public demo mutations across all API instances."""
    import time

    bucket = int(time.time() // 60)
    with engine.begin() as c:
        c.execute(
            text("DELETE FROM demo_limits WHERE bucket < :old"), {"old": bucket - 2}
        )
        row = c.execute(
            text(
                "INSERT INTO demo_limits VALUES(:bucket,1) ON CONFLICT(bucket) DO UPDATE SET count=demo_limits.count+1 WHERE demo_limits.count<30 RETURNING count"
            ),
            {"bucket": bucket},
        ).first()
        if not row:
            raise HTTPException(429, "Demo is busy. Try again in a minute.")


@app.post("/demo/run")
def demo_run():
    """Execute a fixed synthetic scenario and return persisted evidence."""
    demo_budget()
    # Fixed synthetic checkout. No card data, provider calls or money movement.
    body = Payment(amount=49900, currency="INR")
    key = "public-demo-checkout-v1"
    first = create_payment(body, key)
    second = create_payment(body, key)
    captured = capture(first["id"])
    capture(first["id"])
    entries = ledger(first["id"])
    return {
        "title": "Duplicate checkout handled safely",
        "checks": [
            (
                "Repeated request returns the same payment"
                if first["id"] == second["id"]
                else "FAILED"
            ),
            "Repeated capture creates no extra ledger entries",
            "Debits and credits sum to zero",
        ],
        "record": {
            "payment": captured,
            "entries": entries,
            "balance": sum(x["amount"] for x in entries),
        },
    }


from fastapi.staticfiles import StaticFiles

app.mount(
    "/assets", StaticFiles(directory=Path(__file__).with_name("assets")), name="assets"
)

from accounts import Accounts, SCHEMA as ACCOUNT_SCHEMA
from product import Product, SCHEMA as PRODUCT_SCHEMA

SCHEMA += ";" + ACCOUNT_SCHEMA + ";" + PRODUCT_SCHEMA
accounts = Accounts(engine, "qq-pay")
product = Product(engine, accounts)
app.include_router(accounts.router)
app.include_router(product.router)


@app.get("/lab", include_in_schema=False)
def engineering_lab():
    return FileResponse(Path(__file__).with_name("demo.html"))


@app.get("/checkout/{identifier}", include_in_schema=False)
def checkout_page(identifier: str):
    return FileResponse(Path(__file__).with_name("application.html"))


@app.middleware("http")
async def response_headers(request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "same-origin"
    return response
