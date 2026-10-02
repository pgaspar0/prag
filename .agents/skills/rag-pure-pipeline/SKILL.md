---
name: rag-pure-pipeline
description: >-
  Use this skill to implement the pure Python RAG workflow: PDF page extraction with PyMuPDF,
  chunking with page metadata, vector embedding with Gemini, cosine threshold filtering,
  and anti-hallucination structured responses with page citations.
---

# Pure Python RAG Pipeline (No Framework Wrappers)

This skill describes the exact end-to-end RAG implementation without heavy abstractions like LangChain, ensuring full control over citations, chunking, and hallucination prevention.

## Architecture & Principles

1. **Page-Aware Ingestion**: PDFs are processed page-by-page using PyMuPDF (`fitz`). Every chunk is strictly tagged with its origin `page_number`.
2. **Embedding**: Chunks are embedded using Google Gemini `text-embedding-004` (768 dimensions).
3. **Similarity Filtering (Anti-Hallucination Gate 1)**: Before calling the generation model, the highest similarity score is evaluated. If `max_similarity < 0.70`, the system immediately rejects the query with:
   *"Não encontrei esta informação nos documentos fornecidos."* (Zero token waste and zero hallucination risk).
4. **Hermetic System Prompt & Structured Output (Anti-Hallucination Gate 2)**:
   The LLM is strictly constrained via JSON Schema:
   ```json
   {
     "found": true,
     "answer": "O prazo de cancelamento sem penalização é de 15 dias úteis.",
     "citations": [
       {
         "page": 3,
         "exact_quote": "O contratante poderá rescindir o presente contrato sem penalidades no prazo de 15 dias úteis"
       }
     ]
   }
   ```

---

## 1. PDF Page Extraction & Chunking

```python
import fitz  # PyMuPDF
from typing import List, Dict, Any

def extract_chunks_from_pdf(pdf_path: str, chunk_size: int = 600, chunk_overlap: int = 80) -> List[Dict[str, Any]]:
    doc = fitz.open(pdf_path)
    chunks = []
    
    for page_idx, page in enumerate(doc):
        page_num = page_idx + 1
        text = page.get_text("text").strip()
        if not text:
            continue
            
        # Sliding window chunking on text preserving page_number
        start = 0
        chunk_idx = 0
        while start < len(text):
            end = min(start + chunk_size, len(text))
            chunk_content = text[start:end].strip()
            
            if chunk_content:
                chunks.append({
                    "page_number": page_num,
                    "chunk_index": chunk_idx,
                    "content": chunk_content,
                    "char_count": len(chunk_content)
                })
                chunk_idx += 1
                
            start += chunk_size - chunk_overlap
            
    doc.close()
    return chunks
```

---

## 2. Gemini Embeddings & Generation

Using the modern `google-genai` SDK:

```python
from google import genai
from google.genai import types
import json

client = genai.Client(api_key="GEMINI_API_KEY")

def get_embedding(text: str) -> list[float]:
    response = client.models.embed_content(
        model="text-embedding-004",
        contents=text,
    )
    return response.embeddings[0].values

def generate_rag_answer(query: str, contexts: list[dict]) -> dict:
    formatted_context = "\n\n".join([
        f"[Página {c['page_number']}]: {c['content']}" for c in contexts
    ])

    system_instruction = (
        "És um assistente rigoroso de análise de documentos. "
        "A tua tarefa é responder à pergunta do utilizador USANDO EXCLUSIVAMENTE o contexto fornecido abaixo. "
        "REGRAS INEGOCIÁVEIS:\n"
        "1. Se o contexto não contiver a resposta exata, define 'found' como false, 'citations' como [] e responde educadamente que a informação não foi encontrada no documento.\n"
        "2. Nunca uses conhecimento prévio ou suposições externas.\n"
        "3. Para cada afirmação, inclui a citação exata com o número da página correspondente.\n"
        "4. Responde estritamente em formato JSON válido."
    )

    prompt = f"Contexto dos documentos:\n{formatted_context}\n\nPergunta do utilizador: {query}"

    response = client.models.generate_content(
        model="gemini-2.0-flash",
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=system_instruction,
            response_mime_type="application/json",
            temperature=0.0
        )
    )

    return json.loads(response.text)
```
