import re
from typing import Any, Dict, List, Tuple
import fitz  # PyMuPDF


def extract_pages_with_words(pdf_path: str) -> List[Dict[str, Any]]:
    """
    Extracts text, word bounding boxes, and dimensions page-by-page.
    Also detects and strips repetitive headers/footers appearing in > 50% of pages
    within the top and bottom 10% height bands.
    """
    doc = fitz.open(pdf_path)
    total_pages = len(doc)
    raw_pages = []

    # First pass: collect words and potential header/footer lines per page
    header_footer_candidates: Dict[str, int] = {}

    for page_idx, page in enumerate(doc):
        page_num = page_idx + 1
        page_rect = page.rect
        page_w = page_rect.width
        page_h = page_rect.height

        top_band = page_h * 0.10
        bottom_band = page_h * 0.90

        # get_text("words") returns tuples: (x0, y0, x1, y1, word, block_no, line_no, word_no)
        words = page.get_text("words")

        # Group words by line to identify repetitive headers/footers
        lines: Dict[Tuple[int, int], List[Tuple]] = {}
        for w in words:
            key = (w[5], w[6])  # (block_no, line_no)
            lines.setdefault(key, []).append(w)

        page_data = {
            "page_num": page_num,
            "width": page_w,
            "height": page_h,
            "words": words,
            "lines": lines,
            "top_band": top_band,
            "bottom_band": bottom_band,
        }
        raw_pages.append(page_data)

        if total_pages > 1:
            for (block_no, line_no), line_words in lines.items():
                min_y = min(w[1] for w in line_words)
                max_y = max(w[3] for w in line_words)
                if min_y < top_band or max_y > bottom_band:
                    line_text = " ".join(w[4] for w in line_words).strip().lower()
                    # Only consider non-empty lines with letters/numbers
                    if len(line_text) >= 3 and not line_text.isdigit():
                        header_footer_candidates[line_text] = (
                            header_footer_candidates.get(line_text, 0) + 1
                        )

    doc.close()

    # Threshold for repetitive lines: present in > 50% of pages
    repetitive_threshold = total_pages * 0.50
    banned_lines = {
        text for text, count in header_footer_candidates.items()
        if count >= repetitive_threshold
    }

    # Second pass: filter out banned header/footer words and build clean page word lists
    cleaned_pages = []
    for page in raw_pages:
        clean_words = []
        for (block_no, line_no), line_words in page["lines"].items():
            min_y = min(w[1] for w in line_words)
            max_y = max(w[3] for w in line_words)
            line_text = " ".join(w[4] for w in line_words).strip().lower()

            # If line is in header/footer band and matches banned repetitive patterns, skip it
            if (min_y < page["top_band"] or max_y > page["bottom_band"]) and line_text in banned_lines:
                continue

            clean_words.extend(line_words)

        # Sort words in natural reading order: top-to-bottom, left-to-right
        clean_words.sort(key=lambda w: (w[1], w[0]))

        cleaned_pages.append({
            "page_num": page["page_num"],
            "width": page["width"],
            "height": page["height"],
            "words": clean_words,
        })

    return cleaned_pages
