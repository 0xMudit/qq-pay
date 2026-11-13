import uuid
from pydantic import BaseModel, Field
TITLE = "QQ Pay · sandbox"
SCHEMA = """CREATE TABLE IF NOT EXISTS payments (id TEXT PRIMARY KEY, idem TEXT UNIQUE NOT NULL, amount BIGINT NOT NULL, currency TEXT NOT NULL, status TEXT NOT NULL); CREATE TABLE IF NOT EXISTS ledger (id TEXT PRIMARY KEY, payment TEXT NOT NULL, account TEXT NOT NULL, amount BIGINT NOT NULL)"""
import os, secrets
from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, Header, HTTPException
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool
engine = create_engine(os.getenv("DATABASE_URL", "sqlite:///data.db"), **({"connect_args":{"check_same_thread":False}, "poolclass":StaticPool} if os.getenv("DATABASE_URL", "").endswith(":memory:") else {}))
def auth(x_api_key: str = Header(default="")):
    if not secrets.compare_digest(x_api_key, os.environ["API_KEY"]):
        raise HTTPException(401, "Invalid API key")
@asynccontextmanager
async def lifespan(app):
    if len(os.getenv("API_KEY", "")) < 16:
        raise RuntimeError("Set API_KEY to at least 16 characters")
    with engine.begin() as c:
        for statement in SCHEMA.split(";"):
            if statement.strip(): c.execute(text(statement))
    yield
app = FastAPI(title=TITLE, version="0.1.0-beta.1", lifespan=lifespan)
@app.get("/health")
def health():
    with engine.connect() as c: c.execute(text("SELECT 1"))
    return {"status":"ok"}

class Payment(BaseModel):
    amount: int = Field(strict=True, gt=0, le=100000000)
    currency: str = Field(pattern="^(INR|USD|EUR)$")
@app.post("/payments", dependencies=[Depends(auth)])
def create_payment(body: Payment, idempotency_key: str = Header(min_length=8,max_length=128)):
    identifier=str(uuid.uuid4())
    with engine.begin() as c:
        c.execute(text("INSERT INTO payments VALUES(:id,:key,:amount,:currency,'pending') ON CONFLICT(idem) DO NOTHING"),dict(id=identifier,key=idempotency_key,**body.model_dump()))
        row=dict(c.execute(text("SELECT * FROM payments WHERE idem=:key"),dict(key=idempotency_key)).mappings().one())
        if row['amount']!=body.amount or row['currency']!=body.currency: raise HTTPException(409,"Idempotency key reused with different request")
        return row
@app.post("/payments/{identifier}/capture", dependencies=[Depends(auth)])
def capture(identifier: str):
    with engine.begin() as c:
        row=c.execute(text("UPDATE payments SET status='captured' WHERE id=:id AND status='pending' RETURNING *"),dict(id=identifier)).mappings().first()
        if row:
            for account,amount in [('sandbox_clearing',-row['amount']),('merchant_payable',row['amount'])]:
                c.execute(text("INSERT INTO ledger VALUES(:id,:payment,:account,:amount)"),dict(id=str(uuid.uuid4()),payment=identifier,account=account,amount=amount))
        payment=c.execute(text("SELECT * FROM payments WHERE id=:id"),dict(id=identifier)).mappings().first()
        if not payment: raise HTTPException(404,"Payment not found")
        return dict(payment)
@app.get("/payments/{identifier}/ledger", dependencies=[Depends(auth)])
def ledger(identifier: str):
    with engine.connect() as c: return [dict(r) for r in c.execute(text("SELECT * FROM ledger WHERE payment=:id"),dict(id=identifier)).mappings()]
