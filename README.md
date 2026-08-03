# War Room Credit Friendly Homes Disposition OS

Owner-finance marketing, landing pages, SEO, buyer growth, compliance, and disposition automation for Credit Friendly Homes.

> This is a public code repository. Never commit real credentials, buyer information, applications, or production property records.

## Current features

- Password-protected Streamlit application
- Supabase-backed permanent property and buyer storage
- Safe demo fallback when Supabase is not connected
- Owner-finance property intake and launch validation
- 14-channel marketing registry
- `Approve & Launch Everywhere` readiness plan
- Buyer intake and property matching
- Facebook Marketplace compliance guard
- Fictional sample data
- Automated tests and GitHub Actions

## Production setup

See [`docs/SETUP_SUPABASE.md`](docs/SETUP_SUPABASE.md).

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

## Security

The repository contains code only. Real records live in Supabase. Credentials live in Streamlit Secrets. The public Streamlit URL is protected by an application password.
