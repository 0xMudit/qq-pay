SET search_path TO qq_pay;
CREATE INDEX IF NOT EXISTS beta_events_payment ON beta_events(payment,created);
CREATE TABLE IF NOT EXISTS beta_checkout_expiry (payment TEXT PRIMARY KEY REFERENCES beta_payments(id), expires DOUBLE PRECISION NOT NULL);
CREATE TABLE IF NOT EXISTS beta_refunds (id TEXT PRIMARY KEY, payment TEXT NOT NULL REFERENCES beta_payments(id), idem TEXT NOT NULL, amount BIGINT NOT NULL CHECK(amount>0), requested_amount BIGINT, reason TEXT NOT NULL, created DOUBLE PRECISION NOT NULL, UNIQUE(payment,idem));
