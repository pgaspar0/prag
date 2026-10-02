from typing import Any, Dict, List


def create_chunks_from_pages(
    pages: List[Dict[str, Any]],
    target_words: int = 180,
    overlap_words: int = 25,
) -> List[Dict[str, Any]]:
    """
    Creates chunks from extracted pages:
    - Target chunk size ~180-220 words (~250 tokens).
    - Overlap ~25 words (~15%).
    - Invariant: A chunk NEVER spans more than 2 pages (page_end - page_start <= 1).
    - Preserves bounding boxes for all words in the chunk to support highlight overlays.
    """
    # Flatten words with explicit page attribution
    flattened_words = []
    for page in pages:
        page_num = page["page_num"]
        for w in page["words"]:
            flattened_words.append({
                "page": page_num,
                "x0": round(w[0], 2),
                "y0": round(w[1], 2),
                "x1": round(w[2], 2),
                "y1": round(w[3], 2),
                "text": w[4],
            })

    if not flattened_words:
        return []

    chunks = []
    start_idx = 0
    chunk_index = 0
    total_words = len(flattened_words)

    while start_idx < total_words:
        # Proposed end index
        end_idx = min(start_idx + target_words, total_words)

        # Enforce max 2 pages invariant
        chunk_words = flattened_words[start_idx:end_idx]
        first_page = chunk_words[0]["page"]
        
        # If words in this window span more than 2 pages, truncate window
        valid_end_idx = end_idx
        for idx in range(len(chunk_words) - 1, -1, -1):
            if chunk_words[idx]["page"] - first_page > 1:
                valid_end_idx = start_idx + idx
            else:
                break

        # In case a single page is very long, valid_end_idx will just be on page 1 or 2
        actual_end_idx = max(start_idx + 1, valid_end_idx)
        selected_words = flattened_words[start_idx:actual_end_idx]

        chunk_text = " ".join(w["text"] for w in selected_words)
        page_start = selected_words[0]["page"]
        page_end = selected_words[-1]["page"]

        bboxes = [
            {
                "page": w["page"],
                "x0": w["x0"],
                "y0": w["y0"],
                "x1": w["x1"],
                "y1": w["y1"],
            }
            for w in selected_words
        ]

        chunks.append({
            "chunk_index": chunk_index,
            "page_start": page_start,
            "page_end": page_end,
            "text": chunk_text,
            "bboxes": bboxes,
        })
        chunk_index += 1

        if actual_end_idx >= total_words:
            break

        # Move forward by (window - overlap)
        step = max(1, (actual_end_idx - start_idx) - overlap_words)
        start_idx += step

    return chunks
