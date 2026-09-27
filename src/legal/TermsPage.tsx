/**
 * Terms of Service.
 *
 * Deliberately factual. Where Captionline's operating entity, address, or
 * jurisdiction are not published yet, the page says so instead of naming one:
 * inventing a company or a governing state would be worse than an open clause.
 * The single configurable value is the governing law, read from
 * VITE_GOVERNING_LAW (see `src/legal/config.ts`).
 *
 * Accuracy note kept in sync with the product: transcription is real, subtitle
 * (.srt) export and finished MP4 rendering are both real, and included on
 * every plan. The Terms say exactly that, with no promise of anything that is
 * not implemented.
 */

import { usePageMeta } from "../seo/meta";
import { CONTACT_PATH } from "../auth/route";
import { LegalLink, LegalPage } from "./LegalPage";
import type { LegalSection } from "./LegalPage";
import { GOVERNING_LAW, GOVERNING_LAW_PENDING, SUPPORT_EMAIL_PENDING } from "./config";

export function TermsPage() {
  usePageMeta({
    title: "Terms of Service",
    description:
      "Terms of Service for Captionline: plans, processing allowances, ownership of uploaded media, refunds, and liability.",
    path: "/terms",
  });

  const sections: LegalSection[] = [
    {
      id: "acceptance",
      heading: "1. Acceptance of these Terms",
      body: (
        <>
          <p>
            These Terms of Service ("Terms") are the agreement between you and Captionline, the
            video captioning service offered at this website. They apply to every visitor and every
            account, whether or not you pay for a plan.
          </p>
          <p>
            By creating an account, starting a transcription, or otherwise using Captionline, you
            accept these Terms and the Privacy Policy. If you do not accept them, do not use the
            service. If you use Captionline on behalf of an organization, you confirm you have
            authority to accept these Terms for that organization, and "you" then refers to it.
          </p>
        </>
      ),
    },
    {
      id: "the-service",
      heading: "2. What Captionline does",
      body: (
        <>
          <p>Captionline turns video or audio you upload into timed captions that you can then:</p>
          <ul>
            <li>edit, reorder, split, and delete caption cues in a browser-based editor;</li>
            <li>
              style captions in a caption designer: font, size, color, outline, position, spacing,
              and word-by-word highlighting;
            </li>
            <li>preview the captioned result in the browser, with a word-aligned karaoke view;</li>
            <li>download a subtitle file in the widely supported SubRip (.srt) format.</li>
          </ul>
          <p>
            Transcription is performed on Captionline's servers using WhisperX. The file you upload
            is sent to those servers, because the transcription runs there. Caption text, styling,
            and project edits happen in your browser; see the Privacy Policy for exactly what is
            stored and for how long.
          </p>
          <p>
            <strong>Finished-video export is available on every plan</strong>, including the free
            plan, at no additional charge. It renders the video with your captions burned in and
            returns an MP4 for download. Subtitle (.srt) export is also available on every plan.
            Rendering does not consume your monthly processing allowance, so you may export again
            whenever you change the captions or the styling.
          </p>
        </>
      ),
    },
    {
      id: "eligibility",
      heading: "3. Eligibility and accounts",
      body: (
        <>
          <p>
            You may use Captionline if you are at least 16 years old, or the age at which your
            jurisdiction requires a parent or guardian to consent to online services of this kind.
            If you are below that age, do not create an account.
          </p>
          <p>
            You need an account to transcribe. Keep your login details to yourself, use a password
            you do not use anywhere else, and tell us promptly if you think someone else has
            accessed your account. You are responsible for everything done through your account,
            including activity you did not authorize after a compromise you failed to report.
          </p>
          <p>
            You must be old enough to enter the contract you are entering, and you may only use
            Captionline where doing so is lawful. One person or organization, one account, unless
            we agree otherwise in writing.
          </p>
        </>
      ),
    },
    {
      id: "your-responsibilities",
      heading: "4. Your responsibilities",
      body: (
        <>
          <p>
            You are responsible for your account and for the material you put into it. In
            particular, you confirm that you have the right to upload, transcribe and export every
            file you send, and that doing so does not infringe anyone else's rights or break any
            law, contract, or platform rule that applies to you. You also agree to:
          </p>
          <ul>
            <li>provide accurate account details and keep them up to date;</li>
            <li>protect your password and sign out on shared or public devices;</li>
            <li>use your own lawful copies of the media you upload;</li>
            <li>review the captions produced for your file before relying on them.</li>
          </ul>
          <p>
            Automatic speech recognition makes mistakes, especially with accents, background noise,
            overlaps, technical vocabulary, and names. Captionline is a drafting aid, not a
            certified transcript, and you are responsible for checking the output before you
            publish, submit, or rely on it.
          </p>
        </>
      ),
    },
    {
      id: "billing",
      heading: "5. Plans, billing and automatic renewal",
      body: (
        <>
          <p>
            Captionline offers a free plan and paid plans. The prices, features and allowances for
            each plan are the ones shown on the Pricing page when you subscribe; they are set by
            Captionline and can change, as described in section 13.
          </p>
          <p>Paid subscriptions are recurring and renew automatically until you cancel:</p>
          <ul>
            <li>
              a plan billed monthly renews every month until you cancel, at the then-current monthly
              price;
            </li>
            <li>
              a plan billed annually renews every year until you cancel, at the then-current annual
              price. The monthly processing allowance on an annual plan still resets every month.
            </li>
          </ul>
          <p>
            Payment is taken by Stripe. When you subscribe you are sent to Stripe's hosted checkout
            page, where you choose the payment method and see the amount and cadence before you
            authorize anything. Captionline does not see or store your full card details. After the
            first payment, each renewal is charged automatically to the payment method on file until
            you cancel, and a receipt is emailed to you.
          </p>
          <p>
            Prices are in US dollars. Where you are charged by a payment provider or bank in
            another currency, the amount they apply and any currency conversion or cross-border fee
            are set by them, not by Captionline.
          </p>
          <p>
            A plan changes only once Captionline's payment provider confirms payment. If a renewal
            fails, the plan may move to a past-due or canceled state and the paid features may be
            limited until payment succeeds.
          </p>
        </>
      ),
    },
    {
      id: "canceling",
      heading: "6. Canceling a subscription",
      body: (
        <>
          <p>
            You can cancel at any time, from the "Manage subscription" control in your account,
            which opens Stripe's customer portal. There is no cancellation fee and no minimum term
            beyond the period you have already paid for.
          </p>
          <p>
            Canceling stops future renewals. It does not remove the current period: the plan stays
            active, and you keep the paid features, until the end of the period you have already
            paid for. After that, the account returns to the free plan. Deleting your account is a
            separate action, described in the Privacy Policy.
          </p>
        </>
      ),
    },
    {
      id: "refunds",
      heading: "7. Refunds",
      body: (
        <>
          <p>
            Except where the law requires otherwise, payments are not refundable. In particular,
            canceling does not by itself entitle you to a refund of the current period, because
            that period's features remain available to you until it ends.
          </p>
          <p>
            If you have been charged for a period and you did not get what you paid for, or a
            payment was taken in error, contact us before the period ends and we will look at it.
            Where a refund is due by law, we provide it. Any amount refunded is returned to the
            original payment method; it may take your bank a few business days to appear.
          </p>
        </>
      ),
    },
    {
      id: "free-plan",
      heading: "8. The free plan and usage limits",
      body: (
        <>
          <p>
            The free plan needs no payment details and includes a monthly processing allowance and
            the full finished preview. Both figures are the ones shown on the Pricing page and in
            your account, and both can change.
          </p>
          <p>
            Usage limits apply per account and are measured in processing time, that is the duration
            of the media transcribed, not the time you spend editing. The allowance is counted
            against the period in which it resets, is not transferable between accounts, and does
            not roll over into the next period. Where a request would take you past the allowance,
            Captionline rejects it before the transcription runs rather than running it and charging
            you.
          </p>
          <p>
            You may not work around a limit by creating additional accounts, sharing one account,
            or automating sign-up.
          </p>
        </>
      ),
    },
    {
      id: "your-media",
      heading: "9. Your media and your content",
      body: (
        <>
          <p>
            You keep all rights in the media you upload and in the captions you create. Nothing in
            these Terms transfers ownership of your files or your captions to Captionline.
          </p>
          <p>
            You grant Captionline a limited license to host and process the files you submit, for as
            long as it takes to return your transcription, and to keep what you have chosen to save.
            That license is limited to operating, securing and improving the service for you, and
            ends when we delete the file under the Privacy Policy.
          </p>
          <p>
            You are responsible for the media you upload. Do not upload anything you do not have the
            right to upload, and do not upload material that is unlawful, defamatory, or that
            infringes someone else's copyright, privacy, or publicity rights. Where you upload other
            people's footage, music, or voices, you accept responsibility for having the necessary
            permissions.
          </p>
          <p>
            The uploaded file is written to a temporary working directory for the duration of the
            request and is deleted when processing finishes, including when it fails. If the service
            is terminated abnormally, so that step cannot run, the directory is removed by a startup
            cleanup instead; the Privacy Policy describes that case and its time limit. The file is
            not added to a media library, and it is not used to train any model.
          </p>
        </>
      ),
    },
    {
      id: "acceptable-use",
      heading: "10. Acceptable use",
      body: (
        <>
          <p>You must not use Captionline to:</p>
          <ul>
            <li>
              break the law, or infringe copyright, trademark, privacy, publicity, or other rights;
            </li>
            <li>upload malware, or content that is abusive, hateful, or sexually exploitative;</li>
            <li>
              attempt to gain unauthorized access to the service, its servers, or another user's
              account, including by probing, scanning, or bypassing rate limits;
            </li>
            <li>
              interfere with the service, including by overloading it, scraping it at scale, or
              circumventing usage limits, plan entitlements, or preview boundaries;
            </li>
            <li>
              resell, redistribute, or provide a service based on Captionline without our written
              permission;
            </li>
            <li>
              misrepresent automated captions as a human transcription, or otherwise use the output in
              a way that misleads someone about who or what produced it.
            </li>
          </ul>
          <p>
            Transcripts and captions derived from speech can contain sensitive personal information.
            You are responsible for handling the output lawfully, including any recording, disclosure,
            or consent duties that apply to it.
          </p>
        </>
      ),
    },
    {
      id: "intellectual-property",
      heading: "11. Intellectual property",
      body: (
        <>
          <p>
            <strong>Your content.</strong> Your media, your captions, your caption styling, and your
            exported files remain yours. Nothing in these Terms gives Captionline any ownership of
            them.
          </p>
          <p>
            <strong>Captionline's content and software.</strong> The service, including its
            interface, design, code, documentation, and the name and logo "Captionline", belongs to
            Captionline and its licensors. We grant you a limited, revocable, non-exclusive,
            non-transferable license to use the service as intended, for as long as your account is
            in good standing. No other rights are granted, and no rights are granted by
            implication.
          </p>
          <p>
            <strong>Feedback.</strong> If you send us suggestions, we may use them without
            obligation to you, though we will not identify you as its source without permission.
          </p>
        </>
      ),
    },
    {
      id: "availability",
      heading: "12. Availability and support",
      body: (
        <>
          <p>
            Captionline is provided on an as-available basis. We do not promise a specific uptime,
            response time, or processing time. Transcription speed depends on the length of your
            file and on how busy the service is.
          </p>
          <p>
            We may change, suspend, or discontinue any part of the service, including features or
            plan entitlements, and we may limit traffic to protect the service. We will give
            reasonable notice before a material change that reduces functionality you have paid for,
            and we will honor the period you have already paid for.
          </p>
          <p>
            Support is best-effort. Where a support contact address is published on the{" "}
            <LegalLink href={CONTACT_PATH}>Support</LegalLink> page, use it; we will not always be
            able to respond, and we cannot recover media, captions, or account data we hold only for
            as long as the Privacy Policy describes.
          </p>
        </>
      ),
    },
    {
      id: "changes",
      heading: "13. Changes to the service, plans and these Terms",
      /*
       * COMMERCIAL REFUND POLICY: STILL AN OPEN BUSINESS DECISION.
       *
       * An earlier draft of this section promised "a refund of the unused part
       * of the period you paid for" whenever a material change reduced what a
       * customer had paid for. That was an unconditional money-back commitment
       * that nobody approved and that this phase was explicitly not allowed to
       * invent, so it is gone.
       *
       * The clause below therefore commits to nothing beyond what section 7
       * (lawful refunds) already commits to, and says so out loud rather than
       * quietly implying a promise. It is deliberately non-committal and is
       * NOT a finished position: the specific refund policy must be decided,
       * written into this section and section 7 together, and published before
       * paid subscriptions are offered. Do not soften this text into a promise
       * without that decision being made.
       */
      body: (
        <>
          <p>
            We may improve, replace, or retire features, and we may change prices, allowances, and
            plan entitlements. We will tell you before a change that materially reduces the
            functionality or allowance you have paid for, and you may then cancel as described in
            section 6.
          </p>
          <p>
            Captionline's refund position is not published as a matter of policy. Where a refund is
            required by law, we provide it, as section 7 describes. Where a material change to the
            service has been made, a request is handled case by case on its own facts rather than as
            a matter of course. Nothing in this section promises a refund in any particular case,
            and nothing in it excludes one either; the specific policy that will apply is confirmed
            before we offer paid subscriptions.
          </p>
          <p>
            We may revise these Terms. The version and effective date are shown at the top of this
            page. Continued use of Captionline after a change takes effect means you accept the
            revised Terms. If you do not accept them, cancel any subscription and stop using the
            service.
          </p>
        </>
      ),
    },
    {
      id: "termination",
      heading: "14. Suspension and termination",
      body: (
        <>
          <p>
            You may stop using Captionline at any time and delete your account from the account
            panel, which permanently removes your account data as described in the Privacy Policy.
          </p>
          <p>
            We may suspend or close an account, with or without notice, if you break these Terms, in
            particular if you upload unlawful or infringing material, abuse the service, attempt to
            compromise it, or fail to pay. Where the situation allows it, we will tell you what went
            wrong and give you a chance to fix it.
          </p>
          <p>
            Sections that by their nature should survive termination survive it, including
            intellectual property, disclaimers, limitation of liability, indemnity, and governing
            law. Deleting your account does not remove records that Stripe or our hosting, database,
            or email providers must keep, which the Privacy Policy explains.
          </p>
        </>
      ),
    },
    {
      id: "disclaimers",
      heading: "15. Disclaimers",
      body: (
        <>
          <p>
            Captionline is provided "as is" and "as available". To the fullest extent the law
            allows, we disclaim all express, implied and statutory warranties, including implied
            warranties of merchantability, fitness for a particular purpose, accuracy,
            non-infringement, and uninterrupted or error-free operation.
          </p>
          <p>
            Captionline does not warrant that transcription will be accurate, complete, or free of
            error, that the service will always be available, or that the service will meet your
            particular need. Caption output is machine-generated and must be reviewed before use.
          </p>
          <p>
            Nothing in these Terms excludes or limits a right or liability that cannot lawfully be
            excluded or limited, including consumer rights that apply to you.
          </p>
        </>
      ),
    },
    {
      id: "liability",
      heading: "16. Limitation of liability",
      body: (
        <>
          <p>
            To the fullest extent the law allows, Captionline and its operators and suppliers are
            not liable for indirect, incidental, special, consequential or punitive damages, or for
            any loss of profits, revenue, data, goodwill, or business opportunity, arising out of or
            connected with your use of Captionline, even if we were told such a loss was possible.
          </p>
          <p>
            To the fullest extent the law allows, our total liability to you for all claims arising
            out of or related to the service is limited to the total amount you paid Captionline for
            the service in the twelve months before the event giving rise to the claim.
          </p>
          <p>
            Because the service is provided at no charge on the free plan, the same cap applies to
            free accounts, where it may be nil. These limits apply even if a failure was caused by
            our negligence, and they do not apply where the law does not allow liability to be
            limited, for example for death or personal injury caused by negligence, or for fraud.
          </p>
        </>
      ),
    },
    {
      id: "indemnity",
      heading: "17. Indemnity",
      body: (
        <>
          <p>
            You agree to indemnify and hold harmless Captionline and its operators from claims,
            damages, losses, and reasonable costs arising from your use of Captionline, from media or
            content you upload, from captions you publish or distribute, or from your breach of
            these Terms or of any law.
          </p>
          <p>
            This obligation applies to the extent the law allows it, and does not apply to the extent
            a claim arises from our own breach of these Terms or our own infringement of your
            rights.
          </p>
        </>
      ),
    },
    {
      id: "governing-law",
      heading: "18. Governing law and forum",
      body: (
        <>
          {GOVERNING_LAW ? (
            <p>
              These Terms, and any dispute or claim arising out of or in connection with them or
              with the service, are governed by {GOVERNING_LAW}, and the courts there have
              jurisdiction. If you are a consumer, this does not take away any right to bring
              proceedings in the courts of your own country of residence, or any right to mandatory
              consumer protections that apply to you there.
            </p>
          ) : (
            <p className="legal__pending">{GOVERNING_LAW_PENDING}</p>
          )}
        </>
      ),
    },
    {
      id: "term-changes",
      heading: "19. Changes to these Terms",
      body: (
        <p>
          We may update these Terms from time to time. The version and effective date shown at the
          top of this page identify the current text. If a change is significant, we will draw
          attention to it on this page or, where we have your email address, tell you directly.
          Continuing to use Captionline after a change takes effect means you accept the updated
          Terms. Questions about these Terms belong in the first place on the{" "}
          <LegalLink href={CONTACT_PATH}>Support</LegalLink> page.
        </p>
      ),
    },
    {
      id: "contact",
      heading: "20. Contact",
      body: (
        <p>
          Questions about these Terms can be sent through the{" "}
          <LegalLink href={CONTACT_PATH}>Support</LegalLink> page, which shows the current support
          address. Until a support address is configured, {SUPPORT_EMAIL_PENDING}
        </p>
      ),
    },
  ];

  return (
    <LegalPage
      document="terms"
      title="Terms of Service"
      lede="The agreement that governs your use of Captionline. It is written to be read, not to be skimmed past."
      sections={sections}
    />
  );
}

