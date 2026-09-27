import { useCallback, useEffect, useState } from "react";
import { AlertCircle, Check, Loader2 } from "lucide-react";
import { isUnauthorized, useAuth } from "../auth/AuthContext";
import { TERMS_PATH } from "../auth/route";
import { getStoredToken } from "../lib/auth";
import {
  fetchPlans,
  formatAllowance,
  formatPrice,
  openBillingPortal,
  startCheckout,
} from "../lib/billing";
import type { Plan } from "../lib/billing";

const PERIOD_LABELS: Record<string, string> = {
  monthly: "per month",
  annual: "per year",
};

const SESSION_EXPIRED = "Your session expired. Please log in again.";

/**
 * Plain-language renewal disclosure, built from the plan the server returned.
 *
 * Nothing here is hardcoded per plan: the cadence comes from
 * `plan.billing_period` and the allowance from the same payload, so the copy
 * cannot drift away from what Stripe will actually charge.
 */
function renewalDisclosure(plan: Plan): string {
  if (plan.price_usd === 0) {
    return "Free. No card, no renewal, no charge.";
  }

  const minutes = Math.round(plan.usage_allowance_seconds / 60).toLocaleString();

  if (plan.billing_period === "annual") {
    return plan.usage_resets_monthly
      ? `Renews annually until canceled. Includes ${minutes} processing minutes every month.`
      : `Renews annually until canceled. Includes ${minutes} processing minutes.`;
  }

  return plan.usage_resets_monthly
    ? `Renews monthly until canceled. Includes ${minutes} processing minutes every month.`
    : `Renews monthly until canceled. Includes ${minutes} processing minutes.`;
}

export function Pricing() {
  const { status, account, isPaidPlan, refresh, expireSession } = useAuth();
  const [plans, setPlans] = useState<Plan[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [busyPlan, setBusyPlan] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [portalBusy, setPortalBusy] = useState(false);

  const isAuthenticated = status === "authenticated";

  const load = useCallback(async () => {
    setIsLoading(true);
    // Signed-in state only affects which plan is flagged as current.
    const fetched = await fetchPlans(getStoredToken());
    setPlans(fetched);
    setIsLoading(false);
  }, []);

  useEffect(() => {
    void load();
  }, [load, isAuthenticated]);

  // Coming back from Stripe redirects: re-read the server's view of the account.
  useEffect(() => {
    if (isAuthenticated) {
      void refresh();
    }
  }, [isAuthenticated, refresh]);

  const handleSubscribe = async (plan: Plan) => {
    setNotice(null);

    if (!isAuthenticated) {
      setNotice("Create a free account or log in to subscribe.");
      return;
    }

    const token = getStoredToken();
    if (!token) {
      setNotice(SESSION_EXPIRED);
      return;
    }

    setBusyPlan(plan.id);

    try {
      const url = await startCheckout(plan.id, token);

      if (!url) {
        setNotice("Checkout is unavailable right now. Please try again later.");
        return;
      }

      // Hand off to Stripe's hosted page. Nothing about access changes until a
      // verified webhook updates the account on the server.
      window.location.assign(url);
    } catch (error) {
      if (isUnauthorized(error)) {
        // The server rejected the token, so stop claiming to be signed in.
        expireSession();
        setNotice(SESSION_EXPIRED);
        return;
      }

      setNotice(
        error instanceof Error
          ? error.message
          : "Checkout could not be started. Please try again later.",
      );
    } finally {
      setBusyPlan(null);
    }
  };

  const handleManage = async () => {
    const token = getStoredToken();
    if (!token) {
      setNotice(SESSION_EXPIRED);
      return;
    }

    setPortalBusy(true);
    setNotice(null);

    try {
      const url = await openBillingPortal(token);
      if (url) {
        window.location.assign(url);
      }
    } catch (error) {
      if (isUnauthorized(error)) {
        expireSession();
        setNotice(SESSION_EXPIRED);
        return;
      }

      setNotice(error instanceof Error ? error.message : "The billing portal is unavailable.");
    } finally {
      setPortalBusy(false);
    }
  };

  const showPlanNotice = notice !== null;

  return (
    <section className="section section--tight" id="pricing">
      <div className="section__inner">
        <header className="section__head">
          <p className="eyebrow">Pricing</p>
          <h2 className="section__title">Plans that scale with your channel</h2>
          <p className="section__lede">
            Every plan includes full caption editing, the complete caption designer, and .srt subtitle
            export. Paid plans unlock the finished preview and carry a finished-video export
            entitlement — the rendering that turns a project into a video file is not available yet,
            so nothing today produces an MP4.
          </p>
        </header>

        {showPlanNotice ? (
          <p className="pricing__notice" role="status">
            <AlertCircle size={16} aria-hidden="true" />
            {notice}
          </p>
        ) : null}

        {isLoading ? (
          <p className="pricing__loading">
            <Loader2 size={16} className="pricing__spinner" aria-hidden="true" />
            Loading plans…
          </p>
        ) : plans.length === 0 ? (
          // The backend is unreachable or returned nothing. Say so rather than
          // showing stale or invented prices.
          <p className="pricing__notice" role="status">
            Plans are unavailable at the moment. Please try again shortly.
          </p>
        ) : (
          <div className="tiers">
            {plans.map((plan) => {
              const isCurrent = account?.plan === plan.id;
              const isFree = plan.price_usd === 0;

              return (
                <article
                  className={`tier${plan.id === "creator_monthly" ? " tier--featured" : ""}${
                    isCurrent ? " tier--current" : ""
                  }`}
                  key={plan.id}
                >
                  {isCurrent ? <span className="tier__badge">Current plan</span> : null}

                  <h3 className="tier__name">{plan.label}</h3>

                  <p className="tier__price">
                    {formatPrice(plan)}
                    {plan.price_usd > 0 ? (
                      <span className="tier__period">
                        {PERIOD_LABELS[plan.billing_period] ?? ""}
                      </span>
                    ) : null}
                  </p>

                  {plan.annual_savings_usd > 0 ? (
                    <p className="tier__saving">
                      Save ${plan.annual_savings_usd}/year versus monthly billing
                    </p>
                  ) : null}

                  {plan.billing_period === "annual" ? (
                    <p className="tier__billing">Billed annually</p>
                  ) : null}

                  <p className="tier__description">{formatAllowance(plan)}</p>

                  <p className="tier__renewal">{renewalDisclosure(plan)}</p>

                  <ul className="tier__features">
                    <li>
                      <Check size={14} aria-hidden="true" />
                      Full caption editing and styling
                    </li>
                    <li>
                      <Check size={14} aria-hidden="true" />
                      {plan.has_full_preview
                        ? "Full finished-video preview"
                        : `Finished preview limited to ${plan.preview_limit_seconds ?? 30} seconds`}
                    </li>
                    <li>
                      <Check size={14} aria-hidden="true" />
                      {plan.can_export
                        ? "Finished-video export entitlement (renderer not yet available)"
                        : "Finished-video export entitlement on paid plans"}
                    </li>
                    <li>
                      <Check size={14} aria-hidden="true" />
                      Subtitle (.srt) export
                    </li>
                  </ul>

                  {isCurrent ? (
                    isPaidPlan ? (
                      <button
                        className="button button--ghost button--block"
                        type="button"
                        onClick={() => void handleManage()}
                        disabled={portalBusy}
                      >
                        {portalBusy ? "Opening…" : "Manage subscription"}
                      </button>
                    ) : (
                      <button
                        className="button button--ghost button--block"
                        type="button"
                        onClick={() => document.getElementById("upload")?.scrollIntoView({ behavior: "smooth" })}
                      >
                        Go to the editor
                      </button>
                    )
                  ) : isFree ? (
                    <button
                      className="button button--primary button--block"
                      type="button"
                      onClick={() =>
                        document.getElementById("upload")?.scrollIntoView({ behavior: "smooth" })
                      }
                    >
                      Get started
                    </button>
                  ) : (
                    <button
                      className="button button--primary button--block"
                      type="button"
                      onClick={() => void handleSubscribe(plan)}
                      disabled={busyPlan !== null || !plan.purchasable}
                    >
                      {busyPlan === plan.id
                        ? "Opening checkout…"
                        : plan.purchasable
                          ? plan.billing_period === "annual"
                            ? "Subscribe yearly"
                            : "Subscribe"
                          : "Unavailable"}
                    </button>
                  )}

                  {!plan.purchasable && !isFree && !isCurrent ? (
                    <p className="tier__hint">Checkout is not configured for this plan yet.</p>
                  ) : null}
                </article>
              );
            })}
          </div>
        )}

        {/* Cancellation is stated here rather than buried: it is as much a part
            of the offer as the price. */}
        <p className="pricing__footnote">
          Paid plans are a recurring subscription and renew automatically at the price shown until
          you cancel. Cancel any time with <strong>Manage subscription</strong> in your account
          panel: that stops future renewals, and your plan stays active until the end of the period
          you have already paid for. Prices are in US dollars and exclude any tax or duty your
          jurisdiction adds. See the <a href={TERMS_PATH}>Terms of Service</a> for refunds and the
          full terms.
        </p>
      </div>
    </section>
  );
}
