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

## Database and property-photo setup

1. Create a Supabase project.
2. Open **SQL Editor**.
3. Run `database/migrations/001_private_storage.sql` once.
4. Run `database/migrations/002_property_photo_bucket.sql` once.
5. Add the three Streamlit Secrets above.
6. Reboot the Streamlit app.

The first migration enables Row Level Security, revokes browser roles, and grants the server-side service role access to property and buyer records.

The second migration creates a public marketing-photo bucket that accepts JPG, PNG, and WEBP files up to 10 MB. Public access is intentional because those images are used on property landing pages and marketing channels. Upload and delete access stays server-side through the Supabase secret key.

Never upload IDs, contracts, applications, financial documents, or other private records into the property-photo bucket. Never expose the secret key in browser code, GitHub, screenshots, or public documents.

## Local demo mode

When `SUPABASE_URL` and the Supabase secret key are not configured, CommandCore
automatically runs in **demo mode**:

- CRM Home, Leads, Deal Workspace, Owner Approvals, and Marketing use in-memory
  fictional DEMO sample data (fake addresses only).
- A banner reads: `Demo mode — connect Supabase to use real data`.
- Set `COMMANDCORE_DEMO_MODE=1` (environment or Streamlit Secrets) to force demo
  mode even if Supabase credentials are present.

Demo mode never invents live property facts for publishing. Connect Supabase
with the secrets above before using real inventory.
