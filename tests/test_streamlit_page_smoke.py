from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_streamlit_entrypoints_compile() -> None:
    entrypoints = [ROOT / "app.py", *sorted((ROOT / "pages").glob("*.py"))]
    assert entrypoints, "No Streamlit entrypoints found"
    for path in entrypoints:
        source = path.read_text(encoding="utf-8")
        compile(source, str(path), "exec")
