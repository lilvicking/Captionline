import { useCallback, useEffect, useState } from "react";
import { AlertCircle, CheckCircle2, Loader2, Search, Shield } from "lucide-react";
import { useAuth } from "../auth/AuthContext";
import {
  adjustCredit,
  auditActionLabel,
  fetchAdminSummary,
  fetchAudit,
  fetchCustomer,
  fetchCustomerOptions,
  searchCustomers,
} from "../lib/admin";
import type {
  AdminAuditEntry,
  AdminSummary,
  AdminUserDetail,
  AdminUserSummary,
  CustomerOption,
} from "../lib/admin";

/** Friendly credit amounts. Stored server side as seconds regardless. */
const CREDIT_PRESETS = [10, 30, 60, 120];

const REASON_PRESETS = [
  "Transcription issue",
  "Customer support goodwill",
  "Failed processing compensation",
  "Promotion",
  "Manual owner adjustment",
];

function formatDate(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? value
    : date.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

function formatMinutes(seconds: number): string {
  return `${Math.round(seconds / 60).toLocaleString()} min`;
}

export function AdminPage() {
  const { status } = useAuth();

  const [summary, setSummary] = useState<AdminSummary | null>(null);
  const [customerOptions, setCustomerOptions] = useState<CustomerOption[]>([]);
  const [optionsTruncated, setOptionsTruncated] = useState(false);
  const [optionsLoading, setOptionsLoading] = useState(false);
  const [optionsError, setOptionsError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<number | "">("");
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<AdminUserSummary[]>([]);
  const [searching, setSearching] = useState(false);
  const [selected, setSelected] = useState<AdminUserDetail | null>(null);
  const [audit, setAudit] = useState<AdminAuditEntry[]>([]);
  const [loadingDetail, setLoadingDetail] = useState(false);

  const [minutes, setMinutes] = useState(10);
  const [custom, setCustom] = useState("");
  const [reason, setReason] = useState("");
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ tone: "ok" | "error"; text: string } | null>(null);

  const amount = custom.trim() === "" ? minutes : Number(custom);

  const loadSummary = useCallback(async () => {
    try {
      setSummary(await fetchAdminSummary());
    } catch {
      // The console is still usable without the counts.
    }
  }, []);

  useEffect(() => {
    if (status === "authenticated") {
      void loadSummary();
    }
  }, [status, loadSummary]);

  // Load the picker once. Fetched from the server, never bundled, and
  // admin-only, so this is the only place customer addresses are read.
  useEffect(() => {
    if (status !== "authenticated") {
      return;
    }

    const controller = new AbortController();
    let cancelled = false;

    const load = async () => {
      setOptionsLoading(true);
      setOptionsError(null);

      try {
        const result = await fetchCustomerOptions(controller.signal);
        if (cancelled) {
          return;
        }
        setCustomerOptions(result.options);
        setOptionsTruncated(result.truncated);
      } catch (error) {
        if (cancelled || (error instanceof DOMException && error.name === "AbortError")) {
          return;
        }
        setCustomerOptions([]);
        setOptionsError(
          error instanceof Error
            ? error.message
            : "Could not load the customer list. Use search instead.",
        );
      } finally {
        if (!cancelled) {
          setOptionsLoading(false);
        }
      }
    };

    void load();

    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [status]);

  const loadAudit = useCallback(async (id: number) => {
    try {
      setAudit(await fetchAudit(id));
    } catch {
      setAudit([]);
    }
  }, []);

  const handleSearch = async (event: React.FormEvent) => {
    event.preventDefault();
    setMessage(null);

    if (query.trim() === "") {
      return;
    }

    setSearching(true);

    try {
      setResults(await searchCustomers(query));
    } catch (error) {
      setResults([]);
      setMessage({
        tone: "error",
        text: error instanceof Error ? error.message : "Search failed.",
      });
    } finally {
      setSearching(false);
    }
  };

  const handleSelect = async (id: number) => {
    setMessage(null);
    setConfirming(false);
    setLoadingDetail(true);

    try {
      const detail = await fetchCustomer(id);
      setSelected(detail);
      await loadAudit(id);
    } catch (error) {
      setMessage({
        tone: "error",
        text: error instanceof Error ? error.message : "Could not load that account.",
      });
    } finally {
      setLoadingDetail(false);
    }
  };

  /** Choosing from the picker loads the customer straight away. */
  const handlePick = (value: string) => {
    if (value === "") {
      setSelectedId("");
      return;
    }

    setSelectedId(Number(value));
    void handleSelect(Number(value));
  };

  const handleGrant = async () => {
    if (!selected) {
      return;
    }

    if (reason.trim().length < 3) {
      setMessage({ tone: "error", text: "A reason is required for every adjustment." });
      return;
    }

    if (!Number.isFinite(amount) || amount === 0) {
      setMessage({ tone: "error", text: "Enter a non-zero number of minutes." });
      return;
    }

    setBusy(true);
    setMessage(null);

    try {
      const updated = await adjustCredit(selected.id, amount, reason.trim());
      setSelected(updated);
      setConfirming(false);
      setCustom("");
      setReason("");
      await loadAudit(updated.id);
      void loadSummary();
      setMessage({
        tone: "ok",
        text: `Applied ${amount > 0 ? "+" : ""}${amount} minutes to ${updated.email}.`,
      });
    } catch (error) {
      setMessage({
        tone: "error",
        text: error instanceof Error ? error.message : "The adjustment failed.",
      });
    } finally {
      setBusy(false);
    }
  };

  if (status === "loading") {
    return (
      <main className="admin">
        <p className="admin__status">
          <Loader2 size={16} className="pricing__spinner" aria-hidden="true" />
          Checking your session…
        </p>
      </main>
    );
  }

  if (status === "anonymous") {
    return (
      <main className="admin">
        <div className="admin__card">
          <Shield size={22} aria-hidden="true" />
          <h1 className="admin__title">Sign in required</h1>
          <p className="admin__text">
            The support console is only available to signed-in administrators. Use the Account
            button to sign in.
          </p>
        </div>
      </main>
    );
  }

  return (
    <main className="admin">
      <header className="admin__head">
        <p className="eyebrow">Admin</p>
        <h1 className="admin__title">Customer support</h1>
        <p className="admin__text">
          Find a customer, review their plan and usage, and grant goodwill processing credit. Every
          adjustment is recorded.
        </p>
      </header>

      {summary ? (
        <div className="admin__stats">
          <div className="admin__stat">
            <span className="admin__stat-value">{summary.total_users}</span>
            <span className="admin__stat-label">Accounts</span>
          </div>
          <div className="admin__stat">
            <span className="admin__stat-value">{summary.free_users}</span>
            <span className="admin__stat-label">Free</span>
          </div>
          <div className="admin__stat">
            <span className="admin__stat-value">{summary.paid_users}</span>
            <span className="admin__stat-label">Paid</span>
          </div>
          <div className="admin__stat">
            <span className="admin__stat-value">{summary.users_with_credit}</span>
            <span className="admin__stat-label">With credit</span>
          </div>
          <div className="admin__stat">
            <span className="admin__stat-value">
              {formatMinutes(summary.total_bonus_seconds)}
            </span>
            <span className="admin__stat-label">Credit outstanding</span>
          </div>
        </div>
      ) : null}

      <div className="admin__search-block">
        <label className="ctl__label" htmlFor="admin-customer">
          Customer account
        </label>
        <select
          id="admin-customer"
          className="admin__input admin__select"
          value={selectedId}
          onChange={(event) => handlePick(event.target.value)}
          disabled={optionsLoading || customerOptions.length === 0}
        >
          <option value="">
            {optionsLoading
              ? "Loading customers..."
              : customerOptions.length === 0
                ? "No customer accounts"
                : "Select customer..."}
          </option>
          {customerOptions.map((option) => (
            <option key={option.id} value={option.id}>
              {option.email}
            </option>
          ))}
        </select>

        {optionsError ? (
          <p className="admin__message admin__message--error" role="alert">
            <AlertCircle size={15} aria-hidden="true" />
            <span>{optionsError} Use search below instead.</span>
          </p>
        ) : null}

        {optionsTruncated ? (
          <p className="admin__text admin__muted">
            Showing the first {customerOptions.length} accounts. Use search below to reach anyone
            further down the list.
          </p>
        ) : null}
      </div>

      <form className="admin__search" onSubmit={(event) => void handleSearch(event)}>
        <label className="ctl__label" htmlFor="admin-search">
          Search email or account id
        </label>
        <div className="admin__search-row">
          <input
            id="admin-search"
            className="admin__input"
            type="search"
            autoComplete="off"
            placeholder="customer@example.com"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
          <button className="button button--primary" type="submit" disabled={searching}>
            {searching ? (
              <Loader2 size={15} className="pricing__spinner" aria-hidden="true" />
            ) : (
              <Search size={15} aria-hidden="true" />
            )}
            Search
          </button>
        </div>
      </form>

      {results.length > 0 ? (
        <ul className="admin__results">
          {results.map((user) => (
            <li key={user.id}>
              <button
                className="admin__result"
                type="button"
                onClick={() => void handleSelect(user.id)}
              >
                <span className="admin__result-email">{user.email}</span>
                <span className="admin__result-meta">
                  #{user.id} · {user.plan} · {user.subscription_status}
                  {user.is_admin ? " · admin" : ""}
                  {user.bonus_processing_seconds > 0
                    ? ` · ${formatMinutes(user.bonus_processing_seconds)} credit`
                    : ""}
                </span>
              </button>
            </li>
          ))}
        </ul>
      ) : null}

      {loadingDetail ? (
        <p className="admin__status">
          <Loader2 size={16} className="pricing__spinner" aria-hidden="true" />
          Loading account…
        </p>
      ) : null}

      {selected ? (
        <section className="admin__card">
          <h2 className="admin__subtitle">{selected.email}</h2>
          <p className="admin__text admin__muted">
            Account #{selected.id} · joined {formatDate(selected.created_at)}
          </p>

          <dl className="admin__facts">
            <div>
              <dt>Plan</dt>
              <dd>
                {selected.plan_label} ({selected.plan})
              </dd>
            </div>
            <div>
              <dt>Subscription</dt>
              <dd>
                {selected.subscription_status}
                {selected.billed_annually ? " · billed annually" : ""}
              </dd>
            </div>
            <div>
              <dt>Monthly allowance</dt>
              <dd>{formatMinutes(selected.monthly_processing_allowance_seconds)}</dd>
            </div>
            <div>
              <dt>Used this period</dt>
              <dd>{formatMinutes(selected.processing_used_seconds)}</dd>
            </div>
            <div>
              <dt>Support credit</dt>
              <dd>
                {selected.bonus_processing_seconds > 0
                  ? formatMinutes(selected.bonus_processing_seconds)
                  : "None"}
              </dd>
            </div>
            <div>
              <dt>Effective remaining</dt>
              <dd className="admin__strong">
                {formatMinutes(selected.processing_remaining_seconds)}
              </dd>
            </div>
            <div>
              <dt>Usage period</dt>
              <dd>
                resets {formatDate(selected.usage_period_ends_at)}
              </dd>
            </div>
            <div>
              <dt>Full preview</dt>
              <dd>{selected.has_full_preview ? "Yes" : "No"}</dd>
            </div>
            <div>
              <dt>Video export</dt>
              <dd>{selected.can_export ? "Yes" : "No"}</dd>
            </div>
            <div>
              <dt>Account active</dt>
              <dd>{selected.is_active ? "Yes" : "No"}</dd>
            </div>
          </dl>

          <h3 className="admin__subtitle">Grant support credit</h3>
          <p className="admin__text admin__muted">
            Credit is extra, on top of the monthly allowance, and is spent only after that
            allowance is used. It does not reset each month and never changes their plan or
            subscription.
          </p>

          <div className="admin__presets">
            {CREDIT_PRESETS.map((preset) => (
              <button
                key={preset}
                type="button"
                className={`admin__chip${custom.trim() === "" && minutes === preset ? " is-active" : ""}`}
                onClick={() => {
                  setMinutes(preset);
                  setCustom("");
                }}
              >
                +{preset} min
              </button>
            ))}
            <input
              className="admin__input admin__input--inline"
              type="number"
              step="any"
              placeholder="Custom"
              aria-label="Custom minutes"
              value={custom}
              onChange={(event) => setCustom(event.target.value)}
            />
          </div>

          <div className="admin__presets">
            {REASON_PRESETS.map((preset) => (
              <button
                key={preset}
                type="button"
                className={`admin__chip${reason === preset ? " is-active" : ""}`}
                onClick={() => setReason(preset)}
              >
                {preset}
              </button>
            ))}
          </div>

          <input
            className="admin__input"
            type="text"
            placeholder="Reason (required)"
            aria-label="Reason for the adjustment"
            maxLength={280}
            value={reason}
            onChange={(event) => setReason(event.target.value)}
          />

          {confirming ? (
            <div className="admin__confirm" role="alertdialog" aria-label="Confirm adjustment">
              <p className="admin__text">
                <strong>Confirm</strong> {amount > 0 ? "granting" : "removing"}{" "}
                <strong>
                  {amount > 0 ? "+" : ""}
                  {amount} minutes
                </strong>{" "}
                for <strong>{selected.email}</strong>.
              </p>
              <p className="admin__muted">Reason: {reason || "(none)"}</p>
              <div className="admin__confirm-actions">
                <button
                  className="button button--primary"
                  type="button"
                  onClick={() => void handleGrant()}
                  disabled={busy}
                >
                  {busy ? "Applying…" : "Apply"}
                </button>
                <button
                  className="button button--ghost"
                  type="button"
                  onClick={() => setConfirming(false)}
                  disabled={busy}
                >
                  Cancel
                </button>
              </div>
            </div>
          ) : (
            <button
              className="button button--primary button--block"
              type="button"
              onClick={() => setConfirming(true)}
              disabled={busy}
            >
              {amount < 0 ? "Remove credit" : "Grant credit"}
            </button>
          )}

          {message ? (
            <p
              className={`admin__message admin__message--${message.tone}`}
              role="status"
            >
              {message.tone === "ok" ? (
                <CheckCircle2 size={15} aria-hidden="true" />
              ) : (
                <AlertCircle size={15} aria-hidden="true" />
              )}
              <span>{message.text}</span>
            </p>
          ) : null}

          <h3 className="admin__subtitle">Adjustment history</h3>
          {audit.length === 0 ? (
            <p className="admin__text admin__muted">No administrative actions recorded.</p>
          ) : (
            <ul className="admin__audit">
              {audit.map((entry) => (
                <li key={entry.id} className="admin__audit-item">
                  <span className="admin__audit-action">
                    {auditActionLabel(entry.action)}{" "}
                    <strong>
                      {entry.amount_seconds > 0 ? "+" : ""}
                      {entry.amount_seconds} s
                    </strong>
                  </span>
                  <span className="admin__audit-meta">
                    {formatDate(entry.created_at)} · by {entry.admin_email} · {entry.reason}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </section>
      ) : null}
    </main>
  );
}
