# Public Repository Security

This codebase is public. Production data and credentials must live outside GitHub.

## Never commit
- Buyer names, phone numbers, emails, applications, consent records, or call transcripts
- Real property records used for testing
- OpenAI, Supabase, WordPress, REI BlackBook, Meta, Google, TikTok, or YouTube credentials
- Production database dumps
- Private scoring weights or sensitive operational thresholds

## Approved storage
- Streamlit Secrets
- Hosting-provider environment variables
- Supabase with row-level security
- Approved password manager

Before every release, scan the diff and repository for secrets and real customer data.
