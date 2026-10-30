from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/safe_auto_merge_check.py"
SPEC = importlib.util.spec_from_file_location("safe_auto_merge_check", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
is_sensitive = MODULE.is_sensitive


def test_routine_paths_are_not_sensitive() -> None:
    assert (
        is_sensitive(
            [
                "src/cfh_disposition/channels.py",
                "pages/00_CommandCore.py",
                "tests/test_channels.py",
                "README.md",
                "docs/ROADMAP.md",
            ]
        )
        == []
    )


def test_workflow_and_agents_are_sensitive() -> None:
    hits = is_sensitive(
        [
            ".github/workflows/ci.yml",
            "AGENTS.md",
            "docs/PRODUCT_VISION.md",
            "src/cfh_disposition/channels.py",
        ]
    )
    assert hits == [
        ".github/workflows/ci.yml",
        "AGENTS.md",
        "docs/PRODUCT_VISION.md",
    ]


def test_secrets_auth_and_env_are_sensitive() -> None:
    hits = is_sensitive(
        [
            "src/cfh_disposition/auth.py",
            "src/cfh_disposition/auth_helpers.py",
            "src/cfh_disposition/app_secrets.py",
            "docs/my-secret-notes.md",
            "config/credentials.json",
            ".env.example",
            ".streamlit/config.toml",
            "requirements.txt",
            "requirements-dev.txt",
            "pyproject.toml",
        ]
    )
    assert "src/cfh_disposition/auth.py" in hits
    assert "src/cfh_disposition/auth_helpers.py" in hits
    assert "src/cfh_disposition/app_secrets.py" in hits
    assert "docs/my-secret-notes.md" in hits
    assert "config/credentials.json" in hits
    assert ".env.example" in hits
    assert ".streamlit/config.toml" in hits
    assert "requirements.txt" in hits
    assert "requirements-dev.txt" in hits
    assert "pyproject.toml" in hits


def test_database_supabase_migrations_are_sensitive() -> None:
    hits = is_sensitive(
        [
            "database/migrations/001_private_storage.sql",
            "supabase/functions/commandcore-crm-core/index.ts",
            "src/other/migrations/foo.sql",
        ]
    )
    assert hits == [
        "database/migrations/001_private_storage.sql",
        "supabase/functions/commandcore-crm-core/index.ts",
        "src/other/migrations/foo.sql",
    ]


def test_filename_substrings_for_money_legal_and_offers() -> None:
    hits = is_sensitive(
        [
            "pages/50_CommandCore_Contract_Templates.py",
            "src/cfh_disposition/commandcore_offer_engine.py",
            "docs/payment-guide.md",
            "tools/bank_export.py",
            "src/billing_helpers.py",
            "docs/compliance-checklist.md",
            "docs/legal_terms.md",
            "src/signing_flow.py",
            "src/cfh_disposition/channels.py",
        ]
    )
    assert "pages/50_CommandCore_Contract_Templates.py" in hits
    assert "src/cfh_disposition/commandcore_offer_engine.py" in hits
    assert "docs/payment-guide.md" in hits
    assert "tools/bank_export.py" in hits
    assert "src/billing_helpers.py" in hits
    assert "docs/compliance-checklist.md" in hits
    assert "docs/legal_terms.md" in hits
    assert "src/signing_flow.py" in hits
    assert "src/cfh_disposition/channels.py" not in hits


def test_is_sensitive_dedupes_and_normalizes() -> None:
    hits = is_sensitive(["./AGENTS.md", "AGENTS.md", "AGENTS.md"])
    assert hits == ["AGENTS.md"]


def test_cli_returns_nonzero_when_sensitive(tmp_path: Path) -> None:
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, str(SCRIPT), "AGENTS.md", "README.md"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1
    assert "AGENTS.md" in result.stdout
    assert "README.md" not in result.stdout
