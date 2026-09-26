const TIERS = [
  {
    name: "Starter",
    description: "For one-off clips and smaller channels.",
    features: ["Caption minutes", "Standard caption styles", ".srt export"],
  },
  {
    name: "Studio",
    description: "For creators publishing on a schedule.",
    features: ["More caption minutes", "Custom fonts and positioning", ".srt export", "Project history"],
    featured: true,
  },
  {
    name: "Team",
    description: "For teams that need shared workflows.",
    features: ["Shared caption templates", "Review and approvals", "Priority processing"],
  },
];

export function Pricing() {
  return (
    <section className="section section--tight" id="pricing">
      <div className="section__inner">
        <header className="section__head">
          <p className="eyebrow">Pricing</p>
          <h2 className="section__title">Plans are still being finalised</h2>
          <p className="section__lede">
            Phase 1 is a preview build, so there is nothing to pay for yet. Final plans and prices
            will be announced before launch.
          </p>
        </header>

        <div className="tiers">
          {TIERS.map((tier) => (
            <article
              className={`tier${tier.featured ? " tier--featured" : ""}`}
              key={tier.name}
            >
              <h3 className="tier__name">{tier.name}</h3>
              <p className="tier__description">{tier.description}</p>
              <p className="tier__price">Pricing to be announced</p>
              <ul className="tier__features">
                {tier.features.map((feature) => (
                  <li key={feature}>{feature}</li>
                ))}
              </ul>
              <button className="button button--ghost button--block" type="button" disabled>
                Not available yet
              </button>
            </article>
          ))}
        </div>
      </div>
    </section>
  );
}
