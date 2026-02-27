"""
PDF forensic tools — text extraction, image extraction, theoretical term analysis.

Requires PyMuPDF (pymupdf) for full functionality.
Degrades gracefully: returns error evidence if pymupdf is not installed.
"""

import base64
import re
from pathlib import Path


# ---------------------------------------------------------------------------
# PDF text extraction
# ---------------------------------------------------------------------------


def extract_pdf_text(pdf_path: str) -> dict:
    """
    Extract all text from a PDF file.

    Returns:
        {text: str, page_count: int, error: Optional[str]}
    """
    if not pdf_path or not Path(pdf_path).exists():
        return {"text": "", "page_count": 0, "error": f"PDF not found: {pdf_path}"}

    try:
        import fitz  # PyMuPDF
    except ImportError:
        return {"text": "", "page_count": 0, "error": "pymupdf not installed — run: uv add pymupdf"}

    try:
        doc = fitz.open(pdf_path)
        pages_text = []
        for page in doc:
            pages_text.append(page.get_text())
        full_text = "\n".join(pages_text)
        page_count = len(doc)
        doc.close()
        return {"text": full_text, "page_count": page_count, "error": None}
    except Exception as exc:
        return {"text": "", "page_count": 0, "error": str(exc)[:300]}


# ---------------------------------------------------------------------------
# PDF image extraction
# ---------------------------------------------------------------------------


def extract_pdf_images(pdf_path: str) -> dict:
    """
    Extract images from a PDF file as base64-encoded strings.

    Returns:
        {images: list[str], count: int, error: Optional[str]}
    """
    if not pdf_path or not Path(pdf_path).exists():
        return {"images": [], "count": 0, "error": f"PDF not found: {pdf_path}"}

    try:
        import fitz
    except ImportError:
        return {"images": [], "count": 0, "error": "pymupdf not installed"}

    try:
        doc = fitz.open(pdf_path)
        images_b64 = []
        for page in doc:
            for img_info in page.get_images(full=True):
                xref = img_info[0]
                base_image = doc.extract_image(xref)
                img_bytes = base_image["image"]
                # Only include images larger than 5KB (skip tiny icons/bullets)
                if len(img_bytes) > 5000:
                    images_b64.append(base64.b64encode(img_bytes).decode("utf-8"))
        doc.close()
        return {"images": images_b64, "count": len(images_b64), "error": None}
    except Exception as exc:
        return {"images": [], "count": 0, "error": str(exc)[:300]}


# ---------------------------------------------------------------------------
# Theoretical depth analysis
# ---------------------------------------------------------------------------

_THEORETICAL_TERMS = [
    "dialectical synthesis",
    "fan-in",
    "fan-out",
    "metacognition",
    "state synchronization",
    "evidence aggregation",
    "adversarial",
    "persona collusion",
]


def check_theoretical_depth(text: str) -> dict:
    """
    Search PDF text for key theoretical terms from the rubric.
    Checks whether terms appear in substantive context (not just headings).

    Returns:
        {terms_found: list, terms_missing: list, has_depth: bool,
         substantive_count: int}
    """
    text_lower = text.lower()
    found = []
    missing = []

    for term in _THEORETICAL_TERMS:
        if term in text_lower:
            found.append(term)
        else:
            missing.append(term)

    # Check substantive usage: term appears near explanation words
    _explanation_markers = ["because", "implement", "architecture", "design", "pattern", "ensure"]
    substantive_count = 0
    for term in found:
        idx = text_lower.find(term)
        if idx >= 0:
            context = text_lower[max(0, idx - 200):idx + 200]
            if any(marker in context for marker in _explanation_markers):
                substantive_count += 1

    return {
        "terms_found": found,
        "terms_missing": missing,
        "has_depth": substantive_count >= 3,
        "substantive_count": substantive_count,
    }


# ---------------------------------------------------------------------------
# File path extraction and cross-reference
# ---------------------------------------------------------------------------

_PATH_PATTERN = re.compile(r"(?:src/[\w/]+\.py|tests/[\w/]+\.py|rubric\.json|CLAUDE\.md)")


def find_mentioned_paths(text: str) -> list[str]:
    """Extract all source file paths mentioned in PDF text."""
    return sorted(set(_PATH_PATTERN.findall(text)))


def cross_reference_paths(
    mentioned_paths: list[str],
    repo_evidences: dict,
) -> dict:
    """
    Cross-reference file paths from the PDF against detective evidence.

    Returns:
        {verified: list[str], hallucinated: list[str], accuracy_ratio: float}
    """
    # Collect all known locations from evidence
    known_locations = set()
    for ev_list in repo_evidences.values():
        for ev in ev_list:
            if ev.found and ev.location != "N/A":
                known_locations.add(ev.location)

    verified = []
    hallucinated = []

    for path in mentioned_paths:
        # Check if any known location contains this path (partial match)
        if any(path in loc or loc in path for loc in known_locations):
            verified.append(path)
        else:
            hallucinated.append(path)

    total = len(mentioned_paths)
    accuracy = len(verified) / total if total > 0 else 1.0

    return {
        "verified": verified,
        "hallucinated": hallucinated,
        "accuracy_ratio": accuracy,
    }
