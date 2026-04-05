from __future__ import annotations

import json
import subprocess
from pathlib import Path

from .transcript_cleaner import clean_transcript

SUPPORTED_REPORT_SUFFIXES = {".pdf", ".txt", ".md", ".json", ".csv"}


def extract_document_text(path: str) -> str:
    source_path = Path(path).expanduser().resolve()
    suffix = source_path.suffix.lower()
    if suffix not in SUPPORTED_REPORT_SUFFIXES:
        raise ValueError(
            f"Unsupported report format '{suffix or 'unknown'}'. Expected one of {sorted(SUPPORTED_REPORT_SUFFIXES)}."
        )

    if suffix == ".pdf":
        return _extract_pdf_text(source_path)
    if suffix == ".json":
        payload = json.loads(source_path.read_text(encoding="utf-8"))
        return clean_transcript(json.dumps(payload, ensure_ascii=False))
    return clean_transcript(source_path.read_text(encoding="utf-8", errors="ignore"))


def _extract_pdf_text(source_path: Path) -> str:
    try:
        result = subprocess.run(
            ["pdftotext", str(source_path), "-"],
            check=True,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("PDF extraction requires the 'pdftotext' command to be installed.") from exc
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"PDF extraction failed for {source_path.name}: {exc.stderr.strip()}") from exc

    extracted = clean_transcript(result.stdout)
    if not extracted:
        raise RuntimeError(f"No readable text was extracted from {source_path.name}.")
    return extracted
