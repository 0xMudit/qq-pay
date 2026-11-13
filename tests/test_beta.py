import os

os.environ["API_KEY"] = "test-secret-123456"
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
import time
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
import app

ORIGIN = {"origin": "http://testserver"}


@pytest.fixture
def client():
    with TestClient(app.app, headers=ORIGIN) as c:
        # Isolate beta data without relying on test order.
        with app.engine.begin() as db:
            for table in TABLES:
                db.execute(text("DELETE FROM " + table))
        yield c


def signup(client, name="alice"):
    body = {"username": name, "password": "ValidPassword!2026"}
    assert client.post("/api/auth/register", json=body).status_code == 201
    assert client.post("/api/auth/login", json=body).status_code == 200
    return client.get("/api/auth/me").json()


def other_user(client):
    client.post("/api/auth/logout")
    signup(client, "bob")


def test_account_sessions_and_origin(client):
    assert client.get("/api/auth/me").status_code == 401
    signup(client)
    assert client.get("/api/auth/me").json()["username"] == "alice"
    assert (
        client.post(
            "/api/auth/keys",
            json={"label": "test"},
            headers={"origin": "https://evil.example"},
        ).status_code
        == 403
    )
    key = client.post("/api/auth/keys", json={"label": "integration"}).json()["token"]
    assert client.post("/api/auth/logout").status_code == 200
    assert client.get("/api/auth/me").status_code == 401
    assert (
        client.get(
            "/api/auth/me", headers={"authorization": "Bearer " + key}
        ).status_code
        == 200
    )
    keys = client.get(
        "/api/auth/keys", headers={"authorization": "Bearer " + key}
    ).json()
    assert (
        client.delete(
            "/api/auth/keys/" + keys[0]["digest"],
            headers={"authorization": "Bearer " + key},
        ).status_code
        == 200
    )
    assert (
        client.get(
            "/api/auth/me", headers={"authorization": "Bearer " + key}
        ).status_code
        == 401
    )


def test_password_and_duplicate_account(client):
    signup(client)
    assert (
        client.post(
            "/api/auth/register",
            json={"username": "alice", "password": "ValidPassword!2026"},
        ).status_code
        == 409
    )
    assert (
        client.post(
            "/api/auth/login",
            json={"username": "alice", "password": "WrongPassword!2026"},
        ).status_code
        == 401
    )


TABLES = [
    "beta_refunds",
    "beta_checkout_expiry",
    "beta_events",
    "beta_ledger",
    "beta_payments",
    "beta_sessions",
    "beta_users",
    "beta_limits",
]


def test_checkout_capture_refund_and_tenant_isolation(client):
    signup(client)
    body = {
        "title": "Consultation",
        "amount": 49900,
        "currency": "INR",
        "idempotency_key": "checkout-key-123",
    }
    created = client.post("/api/payments", json=body)
    assert created.status_code == 201
    identifier = created.json()["id"]
    assert client.post("/api/payments", json=body).json()["id"] == identifier
    assert client.post("/api/payments", json={**body, "amount": 100}).status_code == 409
    for _ in range(2):
        assert client.post("/api/checkout/" + identifier + "/pay").status_code == 200
    detail = client.get("/api/payments/" + identifier).json()
    assert (
        len(detail["ledger"]) == 2 and sum(e["amount"] for e in detail["ledger"]) == 0
    )
    for _ in range(2):
        assert (
            client.post(
                "/api/payments/" + identifier + "/refund",
                json={"reason": "Requested by customer"},
            ).status_code
            == 200
        )
    detail = client.get("/api/payments/" + identifier).json()
    assert (
        len(detail["ledger"]) == 4 and sum(e["amount"] for e in detail["ledger"]) == 0
    )
    assert client.post("/api/checkout/" + identifier + "/pay").status_code == 409
    other_user(client)
    assert client.get("/api/payments").json() == []
    assert client.get("/api/payments/" + identifier).status_code == 404
    assert (
        client.post(
            "/api/payments/" + identifier + "/refund", json={"reason": "not mine"}
        ).status_code
        == 409
    )


def test_cancelled_checkout_not_payable(client):
    signup(client)
    identifier = client.post(
        "/api/payments",
        json={
            "title": "Cancelled",
            "amount": 100,
            "currency": "USD",
            "idempotency_key": "cancel-key-123",
        },
    ).json()["id"]
    assert client.post("/api/payments/" + identifier + "/cancel").status_code == 200
    assert client.post("/api/checkout/" + identifier + "/pay").status_code == 409


def test_partial_refund_replay_and_reconciliation(client):
    signup(client)
    payment = client.post(
        "/api/payments",
        json={
            "title": "=1+1",
            "amount": 1000,
            "currency": "USD",
            "idempotency_key": "checkout-partial",
        },
    ).json()
    checkout = "/api/checkout/" + payment["id"]
    private = "/api/payments/" + payment["id"]
    assert client.post(checkout + "/pay").status_code == 200
    body = {
        "reason": "Returned item",
        "amount": 250,
        "idempotency_key": "refund-partial",
    }
    first = client.post(private + "/refund", json=body)
    assert first.status_code == 200
    assert client.post(private + "/refund", json=body).json() == first.json()
    assert (
        client.post(private + "/refund", json={**body, "amount": None}).status_code
        == 409
    )
    assert (
        client.post(
            private + "/refund",
            json={**body, "amount": 751, "idempotency_key": "refund-too-much"},
        ).status_code
        == 409
    )
    assert client.get(private).json()["payment"]["refunded_amount"] == 250
    assert (
        client.post(private + "/refund", json={"reason": "Refund remainder"}).json()[
            "refunded_amount"
        ]
        == 1000
    )
    assert client.get("/api/reports/reconciliation").json() == [
        {
            "currency": "USD",
            "captured": 1000,
            "refunded": 1000,
            "net": 0,
            "ledger_balance": 0,
            "entries": 6,
        }
    ]
    assert "'=1+1" in client.get("/api/reports/payments.csv").text
    other_user(client)
    assert client.get("/api/reports/reconciliation").json() == []
    assert "=1+1" not in client.get("/api/reports/payments.csv").text


def test_expired_checkout_cannot_capture(client):
    signup(client)
    body = {
        "title": "Short link",
        "amount": 100,
        "idempotency_key": "checkout-expiry",
        "expires_in_minutes": 1,
    }
    identifier = client.post("/api/payments", json=body).json()["id"]
    assert (
        client.post("/api/payments", json={**body, "expires_in_minutes": 2}).status_code
        == 409
    )
    with app.engine.begin() as db:
        db.execute(
            text("UPDATE beta_checkout_expiry SET expires=0 WHERE payment=:id"),
            {"id": identifier},
        )
    assert client.get("/api/checkout/" + identifier).json()["status"] == "expired"
    assert client.post("/api/checkout/" + identifier + "/pay").status_code == 409
    assert client.get("/api/payments/" + identifier).json()["ledger"] == []
