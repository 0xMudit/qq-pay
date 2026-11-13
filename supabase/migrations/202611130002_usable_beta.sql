SET search_path TO qq_pay;

CREATE TABLE IF NOT EXISTS beta_users (id TEXT PRIMARY KEY, username TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL, created DOUBLE PRECISION NOT NULL);
CREATE TABLE IF NOT EXISTS beta_sessions (digest TEXT PRIMARY KEY, owner TEXT NOT NULL REFERENCES beta_users(id), expires DOUBLE PRECISION NOT NULL, label TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS beta_sessions_owner ON beta_sessions(owner);
CREATE TABLE IF NOT EXISTS beta_limits (key TEXT PRIMARY KEY, count INTEGER NOT NULL, expires DOUBLE PRECISION NOT NULL)
;

CREATE TABLE IF NOT EXISTS beta_payments (id TEXT PRIMARY KEY, owner TEXT NOT NULL REFERENCES beta_users(id), idem TEXT NOT NULL, title TEXT NOT NULL, amount BIGINT NOT NULL CHECK(amount>0), currency TEXT NOT NULL, status TEXT NOT NULL, created DOUBLE PRECISION NOT NULL, UNIQUE(owner,idem));
CREATE INDEX IF NOT EXISTS beta_payments_owner ON beta_payments(owner,created);
CREATE TABLE IF NOT EXISTS beta_ledger (id TEXT PRIMARY KEY, payment TEXT NOT NULL REFERENCES beta_payments(id), account TEXT NOT NULL, amount BIGINT NOT NULL, currency TEXT NOT NULL, kind TEXT NOT NULL, created DOUBLE PRECISION NOT NULL);
CREATE INDEX IF NOT EXISTS beta_ledger_payment ON beta_ledger(payment);
CREATE TABLE IF NOT EXISTS beta_events (id TEXT PRIMARY KEY, payment TEXT NOT NULL REFERENCES beta_payments(id), kind TEXT NOT NULL, note TEXT NOT NULL, created DOUBLE PRECISION NOT NULL)
;
