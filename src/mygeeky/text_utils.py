"""Small text-loading helpers (CV ingestion)."""

from __future__ import annotations

from pathlib import Path


def load_cv_text(path: str) -> str:
    """Load CV text from a .txt/.md file, or a .pdf if the `pdf` extra is installed."""
    p = Path(path).expanduser()
    if not p.exists():
        raise FileNotFoundError(f"CV file not found: {p}")

    if p.suffix.lower() == ".pdf":
        try:
            from pypdf import PdfReader
        except ImportError as exc:
            raise RuntimeError(
                "Reading a .pdf CV requires the optional 'pdf' extra.\n"
                "Install it with: pip install 'mygeeky[pdf]'\n"
                "Or export your CV as .txt/.md and point mygeeky at that instead."
            ) from exc
        reader = PdfReader(str(p))
        return "\n".join(page.extract_text() or "" for page in reader.pages)

    return p.read_text(encoding="utf-8", errors="ignore")
