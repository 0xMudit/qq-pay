# Architecture and guarantees

Clients → idempotent payment intent → simulated capture → balanced ledger. Amounts are integer minor units. A unique idempotency key detects conflicting request reuse. Conditional state updates and ledger inserts share one database transaction. Repeated captures do not duplicate entries. No money moves: this is a deterministic sandbox, with no real provider, card handling, refunds, webhook reconciliation or compliance certification. A real provider integration must preserve atomic local transitions and reconcile uncertain remote outcomes.
