import {
  ArrowUpRight,
  ChartNoAxesCombined,
  CircleDollarSign,
  Download,
} from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Choice, Notice, money, useRecords } from "./shared";

export const currencies = ["INR", "USD", "EUR"];
export function Reports({ currency, onCurrencyChange, overview, rows }) {
  const { rows: report, error } = useRecords("/reports/reconciliation", 8000);
  const totals = report.find((row) => row.currency === currency);
  const days = Array.from({ length: 7 }, (_, index) => {
    const day = new Date();
    day.setHours(0, 0, 0, 0);
    day.setDate(day.getDate() - (6 - index));
    const next = new Date(day);
    next.setDate(next.getDate() + 1);
    const count = rows.filter(
      (row) =>
        row.currency === currency &&
        row.created * 1000 >= +day &&
        row.created * 1000 < +next,
    ).length;
    return {
      label: day.toLocaleDateString(undefined, { weekday: "short" }),
      count,
    };
  });
  const maximum = Math.max(1, ...days.map((day) => day.count));
  return (
    <div className="grid gap-5">
      <Notice>{error}</Notice>
      <div className="merchant-toolbar">
        <Choice
          label="Reporting currency"
          value={currency}
          onChange={onCurrencyChange}
          options={currencies.map((c) => [c, c])}
        />
        <Button asChild variant="outline">
          <a href="/api/reports/payments.csv">
            <Download />
            Export CSV
          </a>
        </Button>
      </div>
      <div className="pay-metrics">
        {[
          ["Captured volume", "captured", CircleDollarSign],
          ["Refunded volume", "refunded", ArrowUpRight],
          ["Net volume", "net", ChartNoAxesCombined],
        ].map(([label, key, Icon]) => (
          <Card key={key}>
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-sm text-muted-foreground">
                <Icon size={16} />
                {label}
              </CardTitle>
            </CardHeader>
            <CardContent className="text-3xl font-semibold tabular-nums">
              {money(totals?.[key] ?? 0, currency)}
            </CardContent>
          </Card>
        ))}
      </div>
      {overview ? (
        <Card>
          <CardHeader>
            <CardTitle>Checkouts created</CardTitle>
            <p className="text-sm text-muted-foreground">
              Last 7 days · {currency}
            </p>
          </CardHeader>
          <CardContent>
            <ul className="payment-chart" aria-label="Checkout count by day">
              {days.map((day) => (
                <li key={day.label}>
                  <span>{day.count}</span>
                  <div className="chart-track">
                    <div
                      style={{ height: (day.count / maximum) * 100 + "%" }}
                    />
                  </div>
                  <span>{day.label}</span>
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      ) : (
        <Card>
          <CardHeader>
            <CardTitle>Ledger reconciliation</CardTitle>
            <p className="text-sm text-muted-foreground">
              Captured and refunded amounts are grouped by currency. A balanced
              ledger sums to zero.
            </p>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  {[
                    "Currency",
                    "Captured",
                    "Refunded",
                    "Net",
                    "Entries",
                    "Ledger balance",
                  ].map((label) => (
                    <TableHead key={label}>{label}</TableHead>
                  ))}
                </TableRow>
              </TableHeader>
              <TableBody>
                {report.map((row) => (
                  <TableRow key={row.currency}>
                    <TableCell>{row.currency}</TableCell>
                    {["captured", "refunded", "net"].map((key) => (
                      <TableCell key={key}>
                        {money(row[key], row.currency)}
                      </TableCell>
                    ))}
                    <TableCell>{row.entries}</TableCell>
                    <TableCell
                      className={
                        row.ledger_balance
                          ? "text-destructive"
                          : "text-emerald-300"
                      }
                    >
                      {row.ledger_balance
                        ? money(row.ledger_balance, row.currency)
                        : "Balanced"}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
            {!report.length && (
              <p className="py-6 text-sm text-muted-foreground">
                Captured payments will appear here.
              </p>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  );
}
