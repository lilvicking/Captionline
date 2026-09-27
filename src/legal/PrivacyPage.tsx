/**
 * Privacy Policy.
 *
 * Written against the architecture that actually exists, not an idealised one.
 * The file you upload *is* sent to the API for transcription, the account
 * record and monthly usage are persisted, and Stripe holds the payment
 * relationship. Claims stronger than that are not made anywhere on this page.
 *
 * Where a support address is needed it comes from VITE_SUPPORT_EMAIL; when that
 * is unset the page says support is not yet available rather than printing an
 * address nobody watches.
 */

import { CONTACT_PATH, PRIVACY_PATH, TERMS_PATH } from "../auth/route";
import { LegalLink, LegalPage } from "./LegalPage";
import type { LegalSection } from "./LegalPage";
import { SUPPORT_EMAIL, SUPPORT_EMAIL_PENDING, supportMailto } from "./config";

function SupportAddress() {
  const mailto = supportMailto();

  if (!mailto || !SUPPORT_EMAIL) {
    return <>{SUPPORT_EMAIL_PENDING}</>;
  }

  return (
    <a href={mailto}>{SUPPORT_EMAIL}</a>
  );
}

export function PrivacyPage() {
  const sections: LegalSection[] = [
    {
      id: "scope",
      heading: "1. What this policy covers",
      body: (
        <>
          <p>
            This policy explains what Captionline collects when you use this website and the
            Captionline service, why it is collected, who else can see it, how long it is kept, and
            what you can ask us to do with it. It applies to the website and to the transcription
            API behind it.
          </p>
          <p>
            It does not cover the media you upload after it has been transcribed and deleted, or the
            captions you create, which stay on your device. It also does not override a separate
            agreement we have with you.
          </p>
        </>
      ),
    },
    {
      id: "account-data",
      heading: "2. Account data we store",
      body: (
        <>
          <p>To give you an account and keep it working, we store:</p>
          <ul>
            <li>
              <strong>your email address</strong>, used to sign you in, to send password reset and
              billing email, and to identify your account;
            </li>
            <li>
              <strong>a password hash</strong>, produced with Argon2id. Your password is never
              stored and never written to a log. The hash cannot be turned back into your password;
            </li>
            <li>
              <strong>hashed session tokens</strong>, so a sign-in can be revoked server-side. The
              browser keeps the token itself; we store only its SHA-256 hash;
            </li>
            <li>
              <strong>usage</strong>: the processing time consumed, measured in seconds, within
              the current monthly period, so your allowance can be enforced and shown;
            </li>
            <li>
              <strong>plan and subscription data</strong>: which plan you are on, your entitlement
              flags, and a copy of the subscription status Stripe reports, so access can be granted
              and revoked. The authoritative billing record lives with Stripe;
            </li>
            <li>
              <strong>account timestamps</strong>, such as when the account was created.
            </li>
          </ul>
          <p>
            The account panel's <em>Delete my account</em> control removes these records, subject to
            the exceptions in section 9.
          </p>
        </>
      ),
    },
    {
      id: "your-media",
      heading: "3. Your media: what happens to an uploaded file",
      body: (
        <>
          <p>
            <strong>The file you upload is sent to the Captionline API.</strong> Transcription runs
            on our servers using WhisperX, so the file has to be uploaded to be transcribed. It is
            not processed inside your browser and we do not claim otherwise.
          </p>
          <p>What happens to it, in order:</p>
          <ol>
            <li>
              the file is streamed to a working directory created for that one request, on the
              server running transcription;
            </li>
            <li>its duration is measured, and your remaining processing allowance is reserved;</li>
            <li>it is transcribed and word-aligned, and the caption track is returned to your
              browser;</li>
            <li>
              the working directory is removed when processing finishes, and also when it fails.
              The file is deleted from that directory on both the success and the failure path.
            </li>
          </ol>
          <p>
            Because the work directory is created per request and removed when the request ends,
            however it ends, we do not keep a copy of your media: it is not added to a library, not
            used to train any model, and not used to improve the service. Transcription is
            synchronous, so in the normal case the file exists on the server for the length of the
            request and no longer.
          </p>
          <p>
            <strong>If the service terminates abnormally.</strong> There is one case in which the
            removal step cannot run: if the service is killed outright, for example by an
            out-of-memory kill, a crash, or a forced restart, then the working directory is left
            behind. Nothing reads it in the meantime. At the next start of the service, any working
            directory left behind by a request that did not finish is deleted, so how long a file can
            remain is bounded by that sweep rather than by the request: with the default setting a
            file is removed at the first start more than <code>TEMP_SWEEP_MAX_AGE_SECONDS</code> (24
            hours by default) after the request, and lowering that setting shortens the window.
          </p>
          <p>
            Two honest caveats. The file necessarily transits the network between your browser and
            our server, and it is written to that server's disk for the duration of the request, so
            it is exposed to that infrastructure while it is there. And our hosting, database and
            email providers process data on our behalf, as listed in section 5.
          </p>
          <p>
            <strong>Captions and projects.</strong> Caption text you edit, styling, and any project
            you assemble are held in your browser's memory as you work. Captionline does not store
            your finished caption track, your project, or your exported file on its servers. If you
            close or reload the page, unsaved edits are lost, so download the .srt file you want to
            keep.
          </p>
        </>
      ),
    },
    {
      id: "use-of-data",
      heading: "4. Why we use this data",
      body: (
        <>
          <ul>
            <li>
              <strong>to provide the service</strong>: authenticating you, transcribing the media
              you submit, enforcing and reporting your monthly processing allowance, and applying
              your plan's preview and export entitlements;
            </li>
            <li>
              <strong>to take payment</strong> and keep plan access in step with what Stripe
              reports;
            </li>
            <li>
              <strong>to keep the service secure and working</strong>: server logs record requests
              and errors, including IP addresses, to investigate abuse, diagnose faults, and enforce
              rate limits;
            </li>
            <li>
              <strong>to send service email</strong>, such as password reset links and payment
              receipts, and to answer the messages you send us;
            </li>
            <li>
              <strong>to comply with our legal obligations</strong> and to enforce our Terms.
            </li>
          </ul>
          <p>
            We do not sell your personal data, and we do not use your media or your captions for
            advertising.
          </p>
        </>
      ),
    },
    {
      id: "subprocessors",
      heading: "5. Who else can see your data",
      body: (
        <>
          <p>
            Captionline relies on a small number of providers. Each of them sees the data needed to
            do its part of the job:
          </p>
          <ul>
            <li>
              <strong>Stripe</strong> handles payments. Card details are entered on Stripe's own
              pages and Captionline never receives or stores them. Stripe holds your billing
              details and its own record of the transactions, and it acts as our payment processor
              and, for subscriptions, as the merchant of record relationship described in the{" "}
              <LegalLink href={TERMS_PATH}>Terms</LegalLink>.
            </li>
            <li>
              <strong>Railway</strong> hosts the website and the transcription API, on infrastructure
              in the United States. Uploaded media passes through this infrastructure while it is
              being transcribed.
            </li>
            <li>
              <strong>Resend</strong> delivers transactional email, including password reset
              messages and payment receipts. It receives the recipient address and the message
              content.
            </li>
            <li>
              <strong>A managed PostgreSQL database</strong> holds the account, usage, and
              subscription-mirror records described in section 2. This database is the store of
              record for your Captionline account.
            </li>
          </ul>
          <p>
            We do not sell or share personal data with advertisers, data brokers, or social networks,
            and we have not set up advertising or analytics cookies.
          </p>
        </>
      ),
    },
    {
      id: "local-storage",
      heading: "6. Cookies and local storage",
      body: (
        <>
          <p>
            Captionline sets no cookies and runs no advertising or analytics trackers. It does use
            your browser's local storage for a single item: the session token issued when you sign
            in, under the key <code>captionline.session.token</code>. That is what keeps you signed
            in across a page reload. It is removed when you log out, when your account is deleted,
            or when the server rejects it.
          </p>
          <p>
            Blocking local storage means you are asked to sign in again on each visit, and the
            transcription service will refuse anonymous uploads.
          </p>
        </>
      ),
    },
    {
      id: "retention",
      heading: "7. How long we keep data",
      body: (
        <>
          <ul>
            <li>
              <strong>Uploaded media</strong>: only for the duration of the transcription request.
              It is deleted from the server's working directory when processing ends, including
              when it fails. If the service is terminated abnormally, it is removed by the startup
              cleanup described in section 3 instead.
            </li>
            <li>
              <strong>Account data</strong> (section 2): for as long as your account exists.
            </li>
            <li>
              <strong>Monthly usage totals</strong>: reset at the start of each monthly period, and
              replaced rather than accumulated indefinitely.
            </li>
            <li>
              <strong>Server logs</strong>: kept for a short operational period, and then deleted.
              They are not kept as a permanent record of your activity.
            </li>
            <li>
              <strong>Billing records</strong>: kept by Stripe for as long as its own legal and tax
              obligations require, which we do not control. See section 9.
            </li>
          </ul>
        </>
      ),
    },
    {
      id: "security",
      heading: "8. Security",
      body: (
        <>
          <p>
            We take reasonable steps to protect the data described in this policy, and you should
            take reasonable steps with yours.
          </p>
          <p>Measures on our side include:</p>
          <ul>
            <li>passwords hashed with Argon2id and never stored or logged in plaintext;</li>
            <li>
              session tokens that are random, stored server-side only as a hash, and revocable;
            </li>
            <li>transmission over HTTPS;</li>
            <li>rate limiting on sensitive endpoints, including sign-in and password reset;</li>
            <li>
              a design in which uploaded media is written to a per-request temporary directory for
              the length of the transcription and removed when it ends, as section 3 describes.
            </li>
          </ul>
          <p>
            No service can promise that data is never accessed. Data may be disclosed where the law
            requires it, for example in response to a valid legal process, and our providers process
            it as set out in section 5. If a breach affects your personal data we will notify you and
            the relevant authority as required. Please also keep your account password to yourself,
            and sign out on shared devices.
          </p>
        </>
      ),
    },
    {
      id: "deletion",
      heading: "9. Deleting your account",
      body: (
        <>
          <p>
            You can delete your account yourself: open the account panel and use{" "}
            <em>Delete my account</em>, which asks for your current password and the confirmation
            word. Deleting requires your subscription to be canceled first, because an active
            subscription must be ended deliberately.
          </p>
          <p>Deleting your account:</p>
          <ul>
            <li>invalidates your sessions, so you are signed out everywhere;</li>
            <li>
              removes your account record, password hash, stored session tokens, and the
              entitlement and plan data held in the Captionline database;
            </li>
            <li>
              stops further collection of new data for the account. There is nothing to delete for
              uploaded media, because it has already been removed from the server when processing
              finished.
            </li>
          </ul>
          <p>
            <strong>What deletion does not erase.</strong> Records held by our providers are outside
            our database and outside our control, and we cannot delete them for you: Stripe retains
            its own financial records of payments, invoices and refunds for the period its legal,
            tax and accounting obligations require, and its customer and payment details remain
            with it. Railway and Resend may retain residual operational records such as delivery
            logs and backups for their own retention periods, and backups are not selectively
            purged. Where a record must be kept by law, we restrict it to the purpose that requires
            it rather than using it for anything else.
          </p>
          <p>
            If you would like data removed that is held by a provider, or you have a question about
            what deletion leaves behind, contact us through the <LegalLink href={CONTACT_PATH}>Support</LegalLink>{" "}
            page.
          </p>
        </>
      ),
    },
    {
      id: "rights",
      heading: "10. Your rights",
      body: (
        <>
          <p>
            Depending on where you live, you may have the right to ask what personal data we hold
            about you, to get a copy of it, to have it corrected or deleted, to restrict or object
            to how we use it, to data portability where it applies, and to be free of decisions made
            solely by automated processing.
          </p>
          <p>
            You can see and export much of your own data already: the account panel shows your email,
            plan, and usage, and the editor lets you download your captions. For anything else,
            contact us and we will deal with the request, including telling you about the safeguards
            that apply to a request for someone else's data.
          </p>
          <p>
            We do not sell personal data, and we do not use it for advertising. Where we cannot
            fulfill a request, we will say so and explain why, for example where a record must be kept
            for tax or fraud-prevention reasons.
          </p>
        </>
      ),
    },
    {
      id: "transfers",
      heading: "11. International processing",
      body: (
        <>
          <p>
            Captionline's providers process data outside your country. Railway hosts the service in
            the United States, the database is hosted there, and Stripe and Resend process data in
            the countries in which they operate. Your account data and your uploaded file may
            therefore be transferred to those countries, which may have different data protection
            rules from yours.
          </p>
          <p>
            Our providers make their own transfer safeguards. If you need information about the
            safeguards that apply to your country, contact us and we will point you at the relevant
            terms.
          </p>
        </>
      ),
    },
    {
      id: "children",
      heading: "12. Children",
      body: (
        <p>
          Captionline is not intended for children. Accounts may only be created by someone old
          enough to enter the contract they are entering, which is 16 or the age of digital consent
          in your jurisdiction, whichever is lower. If you believe a child has created an account,
          tell us through the <LegalLink href={CONTACT_PATH}>Support</LegalLink> page and we will delete it.
        </p>
      ),
    },
    {
      id: "changes",
      heading: "13. Changes to this policy",
      body: (
        <p>
          We may update this policy as the service or the law changes. The version and effective date
          are shown at the top of this page. If a change materially affects how we use data you have
          already given us, we will say so on this page and, where we have your email address, tell
          you directly. Continuing to use Captionline after a change takes effect means you accept
          the updated policy.
        </p>
      ),
    },
    {
      id: "contact",
      heading: "14. Contact",
      body: (
        <>
          <p>
            For any privacy question, request, or complaint, contact us at <SupportAddress /> and we
            will respond as soon as we reasonably can. If you are in the EEA or the UK, you may also
            complain to your local data protection authority.
          </p>
          <p>
            The <LegalLink href={PRIVACY_PATH}>Privacy Policy</LegalLink> and{" "}
            <LegalLink href={TERMS_PATH}>Terms of Service</LegalLink> form the whole of our
            published policy; nothing on this website overrides either of them.
          </p>
        </>
      ),
    },
  ];

  return (
    <LegalPage
      document="privacy"
      title="Privacy Policy"
      lede="What Captionline collects, why, who else sees it, and what you can make us do about it."
      sections={sections}
    />
  );
}
