import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Table,
  TableHeader,
  TableBody,
  TableRow,
  TableHead,
  TableCell,
} from "@/components/ui/table";
import {
  Shell,
  Brand,
  Field,
  Choice,
  Modal,
  Notice,
  Metrics,
  Status,
  action,
  post,
  api,
  money,
  date,
  useRecords,
} from "./shared";
import { toast } from "sonner";

const states = ["pending", "captured", "refunded", "cancelled"];
function Merchant() {
  const { rows, error, refresh } = useRecords("/payments", 8000);
  const [open, setOpen] = useState(false),
    [detail, setDetail] = useState(null),
    [query, setQuery] = useState(""),
    [filter, setFilter] = useState("all"),
    [currency, setCurrency] = useState("INR"),
    [busy, setBusy] = useState(false);
  const key = useRef(crypto.randomUUID());
  const count = (state) => rows.filter((p) => p.status === state).length;
  const total = rows
    .filter((p) => p.status === "captured" && p.currency === "INR")
    .reduce((n, p) => n + p.amount, 0);
  const payment = detail?.payment;
  const openDetail = async (id) => setDetail(await api("/payments/" + id));
  useEffect(() => {
    const latest = rows.find((row) => row.id === payment?.id);
    if (latest && latest.status !== payment.status)
      action(() => openDetail(latest.id));
  }, [rows, payment?.id, payment?.status]);
  return (
    <>
      <div className="page-heading merchant-heading">
        <div>
          <h1>Transactions</h1>
          <p className="text-muted-foreground">
            Create, share, and manage sandbox checkouts.
          </p>
        </div>
        <Button onClick={() => setOpen(true)}>Create checkout</Button>
      </div>
      <Notice>{error}</Notice>
      <Metrics
        values={[
          ["Captured · INR", money(total, "INR")],
          ["Awaiting payment", count("pending")],
          ["Captured", count("captured")],
          ["Refunded", count("refunded")],
        ]}
      />
      <Card>
        <CardHeader>
          <CardTitle>Checkout activity</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-4">
          <div className="flex flex-wrap items-end gap-3">
            <Input
              aria-label="Search checkouts"
              className="max-w-xs"
              placeholder="Search by checkout title"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
            <Choice
              label="Checkout status"
              value={filter}
              onChange={setFilter}
              options={[["all", "All statuses"], ...states.map((s) => [s, s])]}
            />
          </div>
          <Table>
            <TableHeader>
              <TableRow>
                {["Checkout", "Amount", "Status", "Created", ""].map((h) => (
                  <TableHead key={h}>{h}</TableHead>
                ))}
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows
                .filter(
                  (p) =>
                    (filter === "all" || p.status === filter) &&
                    p.title.toLowerCase().includes(query.toLowerCase()),
                )
                .map((p) => (
                  <TableRow key={p.id}>
                    <TableCell>{p.title}</TableCell>
                    <TableCell>{money(p.amount, p.currency)}</TableCell>
                    <TableCell>
                      <Status>{p.status}</Status>
                    </TableCell>
                    <TableCell>{date(p.created)}</TableCell>
                    <TableCell>
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => action(() => openDetail(p.id))}
                      >
                        View checkout
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
            </TableBody>
          </Table>
          {!rows.length && (
            <p className="py-8 text-center text-muted-foreground">
              Create a checkout to get started.
            </p>
          )}
        </CardContent>
      </Card>
      <Modal
        open={open}
        onOpenChange={setOpen}
        title="Create checkout"
        description="Generate a shareable sandbox payment link."
      >
        <form
          className="grid gap-4"
          onChange={() => {
            key.current = crypto.randomUUID();
          }}
          onSubmit={(event) => {
            event.preventDefault();
            const data = new FormData(event.currentTarget);
            setBusy(true);
            action(async () => {
              try {
                const amount = String(data.get("amount"));
                if (!/^\d{1,7}(\.\d{1,2})?$/.test(amount))
                  throw Error("Enter up to two decimal places");
                const [whole, fraction = ""] = amount.split(".");
                const p = await post("/payments", {
                  title: data.get("title"),
                  amount: Number(whole) * 100 + Number(fraction.padEnd(2, "0")),
                  currency,
                  idempotency_key: key.current,
                });
                key.current = crypto.randomUUID();
                setOpen(false);
                await refresh();
                await openDetail(p.id);
              } finally {
                setBusy(false);
              }
            });
          }}
        >
          <Field
            id="title"
            name="title"
            label="Product or service"
            required
            maxLength={160}
          />
          <Field
            id="amount"
            name="amount"
            label="Amount"
            inputMode="decimal"
            placeholder="499.00"
            required
          />
          <Choice
            label="Currency"
            value={currency}
            onChange={(value) => {
              setCurrency(value);
              key.current = crypto.randomUUID();
            }}
            options={["INR", "USD", "EUR"].map((c) => [c, c])}
          />
          <Button disabled={busy}>Create checkout link</Button>
        </form>
      </Modal>
      <Modal
        open={Boolean(payment)}
        onOpenChange={(value) => {
          if (!value) setDetail(null);
        }}
        title={payment?.title || "Checkout details"}
        description="Sandbox checkout, ledger, and activity."
      >
        {payment && (
          <div className="grid gap-4">
            <div className="flex items-center justify-between">
              <strong>{money(payment.amount, payment.currency)}</strong>
              <Status>{payment.status}</Status>
            </div>
            <div className="flex flex-wrap gap-2">
              <Button asChild variant="outline">
                <a
                  href={"/checkout/" + payment.id}
                  target="_blank"
                  rel="noopener"
                >
                  Open checkout
                </a>
              </Button>
              <Button
                variant="outline"
                onClick={() =>
                  action(async () => {
                    await navigator.clipboard.writeText(
                      location.origin + "/checkout/" + payment.id,
                    );
                    toast.success("Checkout link copied");
                  })
                }
              >
                Copy link
              </Button>
              {payment.status === "pending" && (
                <Button
                  variant="destructive"
                  onClick={() =>
                    action(async () => {
                      await post("/payments/" + payment.id + "/cancel");
                      await openDetail(payment.id);
                      await refresh();
                    })
                  }
                >
                  Cancel checkout
                </Button>
              )}
            </div>
            {payment.status === "captured" && (
              <form
                className="grid gap-3"
                onSubmit={(event) => {
                  event.preventDefault();
                  const reason = new FormData(event.currentTarget).get(
                    "reason",
                  );
                  action(async () => {
                    await post("/payments/" + payment.id + "/refund", {
                      reason,
                    });
                    await openDetail(payment.id);
                    await refresh();
                  });
                }}
              >
                <Field
                  id="reason"
                  name="reason"
                  label="Refund reason"
                  minLength={3}
                  maxLength={200}
                  required
                />
                <Button variant="destructive">Issue full sandbox refund</Button>
              </form>
            )}
            <h2>Ledger</h2>
            <Table>
              <TableBody>
                {detail.ledger.map((e) => (
                  <TableRow key={e.id}>
                    <TableCell>
                      {e.kind} · {e.account}
                    </TableCell>
                    <TableCell>{money(e.amount, e.currency)}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
            <h2>Activity</h2>
            {detail.events.map((e) => (
              <p key={e.id} className="text-sm">
                {e.kind} · {date(e.created)} {e.note}
              </p>
            ))}
          </div>
        )}
      </Modal>
    </>
  );
}
function Checkout() {
  const id = location.pathname.split("/")[2];
  const [payment, setPayment] = useState(null),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  const load = () =>
    api("/checkout/" + encodeURIComponent(id)).then(setPayment);
  useEffect(() => {
    load().catch((e) => setError(e.message));
  }, [id]);
  return (
    <main className="center p-4">
      <Card className="w-full max-w-md">
        <CardHeader>
          <Brand />
          <CardTitle>{payment?.title || "Sandbox checkout"}</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-4">
          <Notice>{error}</Notice>
          {payment && (
            <>
              <p>From {payment.merchant}</p>
              <strong className="text-4xl">
                {money(payment.amount, payment.currency)}
              </strong>
              <Status>{payment.status}</Status>
              <Notice>Sandbox payment. No card details are needed.</Notice>
              {payment.status === "pending" && (
                <Button
                  disabled={busy}
                  onClick={() => {
                    setBusy(true);
                    post("/checkout/" + id + "/pay")
                      .then(load)
                      .catch((e) => setError(e.message))
                      .finally(() => setBusy(false));
                  }}
                >
                  Complete sandbox payment
                </Button>
              )}
            </>
          )}
          <a href="/">Back to merchant workspace</a>
        </CardContent>
      </Card>
    </main>
  );
}
export default function App() {
  return <Shell Product={Merchant} Checkout={Checkout} />;
}
