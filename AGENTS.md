# AGENTS.md

## Mission
Build a focused owner-finance disposition operating system for Credit Friendly Homes. Do not add wholesale disposition features to this repository.

## Public repository safety
- Assume every committed file is visible to competitors and the public.
- Never commit credentials, tokens, passwords, API keys, buyer records, applications, or real property records.
- Never commit proprietary scoring weights or internal approval rules that would materially expose the business advantage.
- Use fictional sample data only.
- Store production secrets in Streamlit Secrets or the hosting provider.

## Product rules
- Property facts must be verified before any content is generated or published.
- AI must never invent price, payment, down payment, property condition, repairs, bedrooms, bathrooms, availability, or approval terms.
- Never promise approval or imply that everyone qualifies.
- Preserve Fair Housing compliance and communication consent.
- Facebook Marketplace remains assisted/manual publication; do not build unauthorized browser automation.
- Paid advertising always requires budget approval.
- Sold and pending properties must not launch active campaigns.
- Google Business Profile is optional and not required for launch.

## Engineering rules
- Use Python 3.12, Streamlit, Pydantic, pytest, and Ruff.
- Add tests for important business and compliance logic.
- Keep pull requests small and focused.
- Routine CommandCore pull requests may merge automatically only after all required CI checks pass, the pull request is conflict-free and mergeable, and the verified head SHA has not changed.
- Never auto-merge changes involving credentials or secrets, destructive data changes, legal or compliance decisions, spending or money movement, bank-information changes, signing or binding agreements, major architecture changes, or other consequential owner approvals. Stop for explicit owner approval on those items.
- Do not bypass branch protection, required checks, owner approval gates, or repository safety controls in order to merge.
- Run linting and tests before opening a pull request whenever tools allow; open routine PRs as non-draft when they are ready for CI.
- Use provider adapters so WordPress, OpenAI, REI BlackBook, Supabase, and social integrations can be replaced.
