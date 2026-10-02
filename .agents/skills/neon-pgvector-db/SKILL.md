---
name: neon-pgvector-db
description: >-
  Use this skill to configure, migrate, and query PostgreSQL with pgvector for the RAG project,
  both locally using Docker and in production using Neon Serverless Postgres.
---

# Neon & Docker pgvector Database Skill

This skill defines the database schema, vector extensions, indexing, and similarity search queries for the RAG assistant.

## 1. Local Setup with Docker

Use the official `pgvector` Docker image for local development.

### `docker-compose.yml`
```yaml
services:
  db:
    image: pgvector/pgvector:pg16
    container_name: prag_postgres
    restart: always
    environment:
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: postgrespassword
      POSTGRES_DB: prag_db
    ports:
      - "5432:5432"
    volumes:
      - prag_pgdata:/var/lib/postgresql/data

volumes:
  prag_pgdata:
```

Run locally:
```bash
docker compose up -d
```

---

## 2. Production Setup on Neon

1. Create a project at [neon.tech](https://neon.tech).
2. Copy the Connection String with pooling enabled:
   `postgresql://[user]:[password]@[endpoint]-pooler.neon.tech/[dbname]?sslmode=require`
3. Enable `vector` extension (Neon supports `pgvector` out-of-the-box).

---

## 3. Database Schema

Execute the following DDL script (`scripts/init_db.sql`) to initialize the database:

```sql
-- Enable pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;

-- Table: documents (metadata of uploaded PDFs)
CREATE TABLE IF NOT EXISTS documents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    filename VARCHAR(255) NOT NULL,
    file_path TEXT NOT NULL,
    file_size_bytes BIGINT NOT NULL,
    total_pages INT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- Table: document_chunks (text chunks with page numbers and embeddings)
-- Note: Google text-embedding-004 uses 768 dimensions.
CREATE TABLE IF NOT EXISTS document_chunks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    page_number INT NOT NULL,
    chunk_index INT NOT NULL,
    content TEXT NOT NULL,
    token_count INT NOT NULL,
    embedding vector(768),
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- HNSW index for fast cosine similarity search
CREATE INDEX IF NOT EXISTS idx_chunks_embedding_hnsw 
ON document_chunks 
USING hnsw (embedding vector_cosine_ops)
WITH (m = 16, ef_construction = 64);

-- Index for fast document chunk retrieval
CREATE INDEX IF NOT EXISTS idx_chunks_document_id 
ON document_chunks(document_id);
```

---

## 4. Pure Vector Similarity Query (SQL)

Search for the top $K$ most similar chunks with cosine distance filter:

```sql
SELECT 
    id,
    document_id,
    page_number,
    chunk_index,
    content,
    1 - (embedding <=> :query_embedding) AS similarity
FROM document_chunks
WHERE document_id = :doc_id
  AND (1 - (embedding <=> :query_embedding)) >= :min_similarity_threshold
ORDER BY embedding <=> :query_embedding
LIMIT :limit_k;
```
*Note*: `embedding <=> query` computes cosine distance. `1 - distance` yields cosine similarity (ranging between 0.0 and 1.0).
