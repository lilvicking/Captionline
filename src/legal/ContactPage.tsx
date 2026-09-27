/**
 * Support and contact.
 *
 * Deliberately refuses to invent a postal address, a phone number, or a support
 * mailbox. If VITE_SUPPORT_EMAIL is set, that address is offered; if it is not,
 * the page says email support is not yet available rather than showing an
 * address nobody reads, and points at what does work in the meantime.
 */

import { LifeBuoy, Mail } from "lucide-react";
import { usePageMeta } from "../seo/meta";
import { HOME_PATH, PRIVACY_PATH, TERMS_PATH } from "../auth/route";
import { LegalLink, LegalPage } from "./LegalPage";
import type { LegalSection } from "./LegalPage";
import { SUPPORT_EMAIL, SUPPORT_EMAIL_PENDING, supportMailto } from "./config";

export function ContactPage() {
  usePageMeta({
    title: "Contact and support",
    description: "Support and contact information for Captionline.",
    path: "/contact",
  });

  const mailto = supportMailto();
  const hasSupportEmail = mailto !== null && SUPPORT_EMAIL !== null;

  const sections: LegalSection[] = [
    {
      id: "reach-us",
      heading: "1. How to reach us",
      body: (
        <>
          {hasSupportEmail ? (
            <p>
              Email <a href={mailto}>{SUPPORT_EMAIL}</a> and a person will read it. If your message
              is about an account, use the address on the account so we can find it quickly.
            </p>
          ) : (
            <p className="legal__pending">{SUPPORT_EMAIL_PENDING}</p>
          )}
          <p>
            There is no postal address or phone number for support at the moment, and we would
            rather say that than print details nobody checks. Everything below describes how to
            reach us once email support is switched on.
          </p>
        </>
      ),
    },
    {
      id: "account-help",
      heading: "2. Account, billing and password problems",
      body: (
        <>
          <p>
            Most account problems do not need an email at all:
          </p>
          <ul>
            <li>
              <strong>Forgot your password.</strong> Use <em>Forgot password?</em> on the sign-in
              screen. The link arrives by email and expires in about an hour. Check your spam folder
              if it does not arrive, and note that we give the same answer whether or not the
              address has an account.
            </li>
            <li>
              <strong>Manage or cancel a subscription.</strong> Use{" "}
              <em>Manage subscription</em> in the account panel. It opens Stripe's customer portal,
              where you can update your card, download invoices, and cancel. Canceling stops future
              renewals and your plan stays active until the period you have paid for ends.
            </li>
            <li>
              <strong>A charge you do not recognize.</strong> Invoices and receipts are in the same
              Stripe portal, and each payment is emailed to you.
            </li>
            <li>
              <strong>Delete your account.</strong> Use <em>Delete my account</em> in the account
              panel. It requires your password and the confirmation word, and it needs any
              subscription to be canceled first.
            </li>
          </ul>
        </>
      ),
    },
    {
      id: "technical-issues",
      heading: "3. A transcription did not work",
      body: (
        <>
          <p>
            The messages on the processing screen usually say what went wrong and what to do:
          </p>
          <ul>
            <li>
              <strong>Not signed in.</strong> Transcribing needs an account. Signing in and
              uploading again is the fix.
            </li>
            <li>
              <strong>No processing time left.</strong> Your plan's monthly allowance is used up. It
              resets on the date shown in the account panel, or you can move to a plan with more
              allowance.
            </li>
            <li>
              <strong>File too large, or not readable as video or audio.</strong> Try a different
              file, or re-export it as MP4, MOV, MKV, WebM, MP3, WAV, M4A, FLAC, or OGG.
            </li>
            <li>
              <strong>Service unavailable.</strong> Transcription speed depends on the length of your
              file and on how busy the service is. Trying again shortly usually works.
            </li>
          </ul>
          <p>
            If the caption track came back but the wording is wrong, that is the accuracy of
            automatic speech recognition rather than a fault. Names, accents, background noise, and
            technical terms are the usual culprits, and every cue can be edited in the caption
            track.
          </p>
        </>
      ),
    },
    {
      id: "what-to-include",
      heading: "4. What to include in a message",
      body: (
        <>
          <p>
            So a report can be acted on rather than guessed at, include:
          </p>
          <ul>
            <li>what you were doing and what you expected instead;</li>
            <li>
              the exact message on screen, including any wording from the processing or pricing
              screen;
            </li>
            <li>
              the browser and device you are using, and roughly when it happened. Do not send a
              password, a session token, or full card details.
            </li>
          </ul>
          <p>
            We cannot recover uploaded media or a caption project: the file is deleted from our
            server as soon as it has been transcribed, and your project lives in your browser. Export
            your .srt before you close the page.
          </p>
        </>
      ),
    },
    {
      id: "security",
      heading: "5. Reporting a security problem",
      body: (
        <p>
          If you believe you have found a vulnerability, do not publish it, and do not test against
          other people's accounts. Tell us what you found, how to reproduce it, and what you think
          the impact is, through the address on this page once support email is available. Please
          give us a reasonable window to fix it before disclosing it publicly.
        </p>
      ),
    },
    {
      id: "other-questions",
      heading: "6. Everything else",
      body: (
        <>
          <p>
            Pricing, allowances, and what each plan includes are on the{" "}
            <LegalLink href={`${HOME_PATH}#pricing`}>Pricing</LegalLink> section. Billing terms,
            refunds, and cancellation are set out in the{" "}
            <LegalLink href={TERMS_PATH}>Terms of Service</LegalLink>. What we collect and how long
            we keep it is set out in the <LegalLink href={PRIVACY_PATH}>Privacy Policy</LegalLink>.
          </p>
          <p>
            Where this page cannot give you an answer, it will tell you that rather than invent one.
          </p>
        </>
      ),
    },
  ];

  return (
    <LegalPage
      title="Support"
      lede="How to get help with an account, a subscription, or a transcription that did not work."
      sections={sections}
      note={
        <p className="legal__status">
          {hasSupportEmail ? (
            <>
              <Mail size={15} aria-hidden="true" />
              Support email: <a href={mailto}>{SUPPORT_EMAIL}</a>
            </>
          ) : (
            <>
              <LifeBuoy size={15} aria-hidden="true" />
              {SUPPORT_EMAIL_PENDING} Everything else on this page works today.
            </>
          )}
        </p>
      }
    />
  );
}

