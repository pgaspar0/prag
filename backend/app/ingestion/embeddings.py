import asyncio
import hashlib
import math
from typing import List
import structlog
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_random_exponential

from app.config import settings

logger = structlog.get_logger()

# Semaphore to limit concurrency to Gemini API to prevent 429 errors
_semaphore = asyncio.Semaphore(3)


def normalize_l2(vector: List[float]) -> List[float]:
    """Applies L2 normalization to a vector (required for truncated Matryoshka embeddings)."""
    norm = math.sqrt(sum(x * x for x in vector))
    if norm == 0.0:
        return vector
    return [x / norm for x in vector]


SYNTHETIC_STOPWORDS = {
    "o", "a", "os", "as", "de", "do", "da", "dos", "das", "em", "no", "na", "nos", "nas",
    "um", "uma", "uns", "umas", "por", "pelo", "pela", "pelos", "pelas", "para", "com", "sem",
    "e", "ou", "que", "se", "ao", "aos", "qual", "quais", "quem", "como", "onde", "quando"
}


def generate_synthetic_embedding(text: str, dim: int = 768) -> List[float]:
    """
    Generates a deterministic L2-normalized embedding vector based on a bag-of-words hashing trick.
    Used for local testing, CI, and offline benchmarks when GEMINI_API_KEY is not configured.
    Texts sharing vocabulary will have natural positive cosine similarity.
    """
    import re
    words = [
        w for w in re.findall(r"\w+", text.lower())
        if len(w) > 2 and w not in SYNTHETIC_STOPWORDS
    ]

    if not words:
        h = hashlib.sha256(text.encode("utf-8")).digest()
        values = [(float(h[i % len(h)] - 128) / 128.0) for i in range(dim)]
        return normalize_l2(values)

    vec = [0.0] * dim
    for w in words:
        h = hashlib.md5(w.encode("utf-8")).digest()
        for i in range(16):
            idx = int.from_bytes(h[i:i+2], "little") % dim
            sign = 1.0 if (h[i] % 2 == 0) else -1.0
            vec[idx] += sign

    return normalize_l2(vec)


@retry(
    wait=wait_random_exponential(min=1, max=10),
    stop=stop_after_attempt(4),
    retry=retry_if_exception_type(Exception),
    reraise=True,
)
async def _embed_with_retry(client, text: str, model: str, dim: int, task_type: str) -> List[float]:
    # google-genai embed_content call
    response = await asyncio.to_thread(
        client.models.embed_content,
        model=model,
        contents=text,
        config={
            "output_dimensionality": dim,
            "task_type": task_type,
        },
    )
    raw_vector = response.embeddings[0].values
    return normalize_l2(raw_vector[:dim])


async def generate_embedding(text: str, task_type: str = "RETRIEVAL_DOCUMENT") -> List[float]:
    """
    Generates a normalized embedding for a given text:
    - task_type: RETRIEVAL_DOCUMENT (for chunks) or RETRIEVAL_QUERY (for questions)
    - Output dimension: settings.EMBED_DIM (768)
    """
    if not settings.GEMINI_API_KEY or settings.GEMINI_API_KEY == "your_gemini_api_key_here":
        return generate_synthetic_embedding(text, settings.EMBED_DIM)

    from google import genai
    client = genai.Client(api_key=settings.GEMINI_API_KEY)

    async with _semaphore:
        try:
            return await _embed_with_retry(
                client=client,
                text=text,
                model=settings.EMBED_MODEL,
                dim=settings.EMBED_DIM,
                task_type=task_type,
            )
        except Exception as exc:
            logger.error("gemini_embedding_failed", error=str(exc))
            raise exc


async def generate_embeddings_batch(texts: List[str], task_type: str = "RETRIEVAL_DOCUMENT") -> List[List[float]]:
    """Generates embeddings for a batch of texts concurrently with rate limiting."""
    tasks = [generate_embedding(t, task_type=task_type) for t in texts]
    return await asyncio.gather(*tasks)
