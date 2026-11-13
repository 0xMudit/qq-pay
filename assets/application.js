let payments = [];
let selectedPayment = null;
let paymentKey = crypto.randomUUID();
function renderPayments() {
  const count = (s) => payments.filter((p) => p.status === s).length;
  $("pay-total").textContent = money(
    payments
      .filter((p) => p.currency === "INR" && p.status === "captured")
      .reduce((sum, p) => sum + p.amount, 0),
  );
  $("pay-pending").textContent = count("pending");
  $("pay-captured").textContent = count("captured");
  $("pay-refunded").textContent = count("refunded");
  const rows = payments.filter(
    (p) =>
      (!$("payment-filter").value || p.status === $("payment-filter").value) &&
      p.title.toLowerCase().includes($("payment-search").value.toLowerCase()),
  );
  $("payments-empty").hidden = rows.length > 0;
  $("payment-rows").innerHTML = rows
    .map(
      (p) =>
        "<tr><td><strong>" +
        esc(p.title) +
        '</strong><br><span class="mono muted">' +
        p.id.slice(0, 8) +
        "</span></td><td>" +
        esc(money(p.amount, p.currency)) +
        '</td><td><span class="status ' +
        p.status +
        '">' +
        p.status +
        '</span></td><td class="muted">' +
        esc(stamp(p.created)) +
        '</td><td><button class="ghost" data-payment="' +
        p.id +
        '">View →</button></td></tr>',
    )
    .join("");
}
async function refreshPayments() {
  payments = await api("/payments");
  renderPayments();
  if (selectedPayment && $("payment-detail").open)
    await paymentDetail(selectedPayment, false);
}
async function paymentDetail(id, open = true) {
  selectedPayment = id;
  const data = await api("/payments/" + id),
    p = data.payment;
  $("payment-detail-content").innerHTML =
    "<h3>" +
    esc(p.title) +
    '</h3><div class="row"><strong>' +
    esc(money(p.amount, p.currency)) +
    '</strong><span class="status ' +
    p.status +
    '">' +
    p.status +
    '</span></div><p class="mono muted">' +
    esc(p.id) +
    "</p>";
  $("payment-detail-actions").innerHTML =
    '<button class="secondary" data-copy-link>Copy checkout link</button><a target="_blank" href="/checkout/' +
    p.id +
    '">Open checkout ↗</a>' +
    (p.status === "pending"
      ? '<button class="danger" data-cancel-payment>Cancel checkout</button>'
      : "");
  $("refund-form").hidden = p.status !== "captured";
  $("payment-ledger").innerHTML = data.ledger.length
    ? data.ledger
        .map(
          (l) =>
            '<div class="receipt-line"><span>' +
            esc(l.kind) +
            " · " +
            esc(l.account) +
            "</span><strong>" +
            esc(money(l.amount, l.currency)) +
            "</strong></div>",
        )
        .join("")
    : "<p>No financial entries yet.</p>";
  $("payment-events").innerHTML = data.events
    .map(
      (e) =>
        "<p><strong>" +
        esc(e.kind) +
        "</strong> · " +
        esc(stamp(e.created)) +
        (e.note ? "<br>" + esc(e.note) : "") +
        "</p>",
    )
    .join("");
  if (open) openDialog("payment-detail");
}
$("new-payment").onclick = () => openDialog("payment-dialog");
$("payment-form").oninput = () => (paymentKey = crypto.randomUUID());
$("payment-form").onsubmit = async (event) => {
  event.preventDefault();
  $("create-payment").disabled = true;
  try {
    const raw = $("payment-amount").value.trim();
    if (!/^\d{1,7}(\.\d{1,2})?$/.test(raw))
      throw Error("Enter an amount with up to two decimal places.");
    const [whole, decimal = ""] = raw.split(".");
    const amount = Number(whole) * 100 + Number(decimal.padEnd(2, "0"));
    const p = await post("/payments", {
      title: $("payment-title").value,
      amount,
      currency: $("payment-currency").value,
      idempotency_key: paymentKey,
    });
    paymentKey = crypto.randomUUID();
    $("payment-dialog").close();
    $("payment-form").reset();
    await refreshPayments();
    await paymentDetail(p.id);
    toast("Checkout created. Share the link to try payment.");
  } catch (error) {
    toast(error.message);
  } finally {
    $("create-payment").disabled = false;
  }
};
$("payment-search").oninput = renderPayments;
$("payment-filter").onchange = renderPayments;
$("payment-rows").onclick = (event) => {
  const b = event.target.closest("[data-payment]");
  if (b) paymentDetail(b.dataset.payment).catch((e) => toast(e.message));
};
$("payment-detail-actions").onclick = async (event) => {
  if (event.target.closest("[data-copy-link]"))
    return copy(location.origin + "/checkout/" + selectedPayment);
  if (event.target.closest("[data-cancel-payment]")) {
    try {
      await post("/payments/" + selectedPayment + "/cancel");
      await refreshPayments();
      await paymentDetail(selectedPayment, false);
    } catch (e) {
      toast(e.message);
    }
  }
};
$("refund-form").onsubmit = async (event) => {
  event.preventDefault();
  const button = event.target.querySelector("button");
  button.disabled = true;
  try {
    await post("/payments/" + selectedPayment + "/refund", {
      reason: $("refund-reason").value,
    });
    await refreshPayments();
    await paymentDetail(selectedPayment, false);
    toast("Full sandbox refund recorded");
  } catch (e) {
    toast(e.message);
  } finally {
    button.disabled = false;
  }
};
document.addEventListener("account-ready", () =>
  refreshPayments().catch((e) => toast(e.message)),
);
setInterval(() => {
  if (account && !document.hidden) refreshPayments().catch(() => {});
}, 8000);
async function loadCheckout() {
  const id = location.pathname.split("/")[2];
  const p = await api("/checkout/" + encodeURIComponent(id));
  $("checkout-title").textContent = p.title;
  $("checkout-merchant").textContent = "From " + p.merchant;
  $("checkout-amount").textContent = money(p.amount, p.currency);
  $("checkout-state").textContent = p.status;
  $("checkout-pay").hidden = p.status !== "pending";
  $("checkout-message").textContent =
    p.status === "captured"
      ? "Payment complete. Your sandbox receipt is recorded."
      : p.status === "refunded"
        ? "This sandbox payment was refunded."
        : p.status === "cancelled"
          ? "This checkout was cancelled."
          : "";
}
document.addEventListener("checkout-ready", () => {
  $("auth-view").hidden = true;
  $("workspace").hidden = true;
  $("public-checkout").hidden = false;
  loadCheckout().catch((e) => {
    $("checkout-title").textContent = e.message;
    $("checkout-pay").hidden = true;
  });
});
$("checkout-pay").onclick = async () => {
  $("checkout-pay").disabled = true;
  try {
    await post(
      "/checkout/" +
        encodeURIComponent(location.pathname.split("/")[2]) +
        "/pay",
    );
    await loadCheckout();
  } catch (e) {
    $("checkout-message").textContent = e.message;
  } finally {
    $("checkout-pay").disabled = false;
  }
};
