# War Room Credit Friendly Homes Disposition OS

Owner-finance marketing, landing pages, SEO, buyer growth, compliance, and disposition automation for Credit Friendly Homes.

> This is a public code repository. Never commit real credentials, buyer information, applications, or production property records.

## Current first-build features

- Streamlit executive dashboard
- Owner-finance property intake
- Property launch validation
- 14-channel marketing registry
- `Approve & Launch Everywhere` readiness plan
- Safe deterministic campaign preview before OpenAI is connected
- Buyer-to-property matching preview
- Facebook Marketplace compliance guard
- Fictional sample data
- Automated tests and GitHub Actions

## Local setup

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
streamlit run app.py
```

## Tests

```bash
ruff check .
pytest
```

## Planned integrations

Supabase, Google Sheets, WordPress, OpenAI, REI BlackBook, Meta, Google Ads, Instagram, TikTok, and YouTube will be added through replaceable provider adapters in later pull requests.
