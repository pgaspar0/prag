---
name: fastapi-rag-service
description: >-
  Use this skill to build, configure, and maintain the FastAPI backend for the RAG project,
  including PDF upload handling, PDF file streaming for the viewer, and the search/query API.
---

# FastAPI Backend Service Skill

This skill defines the structure and endpoints for the Python FastAPI backend of the RAG assistant.

## Recommended Project Structure

```text
prag/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI app definition, CORS, lifespan
│   │   ├── config.py            # Environment settings (Pydantic Settings)
│   │   ├── database.py          # SQLAlchemy async engine & sessionmaker
│   │   ├── models.py            # SQLAlchemy models (Document, DocumentChunk)
│   │   ├── schemas.py           # Pydantic schemas (Request/Response)
│   │   ├── services/
│   │   │   ├── storage.py       # Local file storage / Cloudflare R2 client
│   │   │   ├── pdf_parser.py    # PyMuPDF text & page extractor
│   │   │   ├── embedding.py     # Gemini embedding client
│   │   │   └── rag.py           # Similarity query + hermetic LLM generation
│   │   └── routes/
│   │       ├── documents.py     # Upload, list, and serve PDF files
│   │       ├── query.py         # RAG question-answering with citations
│   │       └── evals.py         # Evaluation benchmark triggers
│   ├── storage/                 # Local directory for uploaded PDFs
│   ├── requirements.txt
│   └── Dockerfile
```

---

## Essential Endpoints Specification

### 1. Document Upload (`POST /api/documents/upload`)
- Accepts `multipart/form-data` with `file: UploadFile`.
- Saves file to `./storage/` or Cloudflare R2 bucket.
- Extracts pages using PyMuPDF, chunks text, creates embeddings.
- Saves document record and chunks in PostgreSQL (`pgvector`).
- Returns: `{ "document_id": "...", "filename": "...", "total_pages": 12 }`.

### 2. PDF File Serving (`GET /api/documents/{doc_id}/file`)
- Serves the PDF file with `FileResponse` and `media_type="application/pdf"`.
- Must support HTTP Range headers (status 206 Partial Content) to allow the frontend PDF viewer to load pages on demand without downloading the full document upfront.

### 3. Query with Citations (`POST /api/query`)
- Body:
  ```json
  {
    "document_id": "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d",
    "query": "Qual é a duração da garantia dos serviços?",
    "similarity_threshold": 0.70
  }
  ```
- Flow:
  1. Generate embedding for `query`.
  2. Perform cosine similarity query in `document_chunks`.
  3. If highest similarity $< 0.70$, return:
     ```json
     {
       "found": false,
       "answer": "Não encontrei esta informação nos documentos fornecidos.",
       "citations": [],
       "max_similarity": 0.54
     }
     ```
  4. If relevant chunks exist, feed into Gemini with strict citation prompt and return the JSON response.

---

## FastAPI CORS & Lifespan Setup

```python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(
    title="PRAG - Precise RAG with Citations",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "https://*.vercel.app"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```
