# Supabase and Streamlit Setup

This repository is public. Real credentials and operational data must stay outside GitHub.

## Required Streamlit Secrets

Add these in the Streamlit app's **Manage app → Settings → Secrets** panel:

```toml
APP_PASSWORD = "choose-a-strong-private-password"
SUPABASE_URL = "https://your-project.supabase.co"
SUPABASE_SECRET_KEY = "sb_secret_..."
```

The application also accepts the legacy `SUPABASE_SERVICE_ROLE_KEY`, but new Supabase secret keys are preferred.

## Database setup

1. Create a Supabase project.
2. Open **SQL Editor**.
3. Copy the contents of `database/migrations/001_private_storage.sql`.
4. Run the SQL once.
5. Add the three Streamlit Secrets above.
6. Reboot the Streamlit app.

The migration enables Row Level Security, revokes browser roles, and grants the server-side service role access. Never expose the secret key in browser code, GitHub, screenshots, or public documents.
