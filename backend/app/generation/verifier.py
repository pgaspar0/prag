import re
import unicodedata
from typing import Tuple
from rapidfuzz import fuzz


def normalize_text_for_verification(text: str) -> str:
    """
    Applies strict canonical normalization to text for deterministic string verification:
    1. Unicode NFKC normalization.
    2. Normalize curly quotes and apostrophes to standard ones.
    3. Normalize dashes and hyphens (em-dash, en-dash) to standard hyphens.
    4. Remove soft-hyphens and end-of-line hyphenation breaks: e.g. "compa- \n nhia" -> "companhia".
    5. Collapse multiple whitespace and newline characters into single spaces.
    6. Lowercase and strip.
    """
    if not text:
        return ""

    # 1. Unicode NFKC normalization
    s = unicodedata.normalize("NFKC", text)

    # 2. Normalize quotation marks and apostrophes
    s = re.sub(r"[“”«»]", '"', s)
    s = re.sub(r"[‘’`´]", "'", s)

    # 3. Normalize dashes
    s = re.sub(r"[—–−]", "-", s)

    # 4. Remove end-of-line hyphenation across newlines or spaces
    s = re.sub(r"(\w+)-\s*\n\s*(\w+)", r"\1\2", s)
    s = re.sub(r"(\w+)\xad(\w+)", r"\1\2", s)  # Soft hyphen \xad

    # 5. Collapse all whitespace into a single space
    s = re.sub(r"\s+", " ", s)

    # 6. Lowercase and strip
    return s.strip().lower()


def verify_citation_quote(quote: str, chunk_text: str) -> Tuple[bool, str]:
    """
    Deterministically verifies that the cited quote exists within the chunk text.
    First checks for exact substring match after canonical normalization.
    If not exact substring, allows a high-confidence fuzzy match (partial_ratio >= 95).

    Returns:
        Tuple[bool, str]: (is_valid, method)
    """
    norm_quote = normalize_text_for_verification(quote)
    norm_chunk = normalize_text_for_verification(chunk_text)

    # Reject trivial or empty citations
    if len(norm_quote) < 8:
        return False, "quote_too_short"

    # 1. Exact substring check (Primary Gate)
    if norm_quote in norm_chunk:
        return True, "exact_substring"

    # 2. Fuzzy partial match fallback (e.g. OCR artifacts or whitespace punctuation variances)
    ratio = fuzz.partial_ratio(norm_quote, norm_chunk)
    if ratio >= 95:
        return True, f"fuzzy_ratio_{ratio}"

    return False, f"mismatch_ratio_{ratio}"
