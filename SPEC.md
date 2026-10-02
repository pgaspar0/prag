# PRAG — Precise RAG with Citations & Benchmarks

> Documento de contexto fixo para o agente de código. Lê-o por inteiro antes de cada sessão.
> Regra de ouro: **uma fase = uma sessão = um commit**. Não implementes nada fora do âmbito descrito.

---

## 0. Objectivo e posicionamento

Assistente de perguntas e respostas sobre PDFs (contratos, manuais, políticas) que:

1. **Cita** cada afirmação com a página exacta, e o leitor de PDF salta e **destaca** a passagem.
2. **Recusa de forma mensurável** quando a resposta não está nos documentos.
3. **Mede-se a si próprio**: dashboard de avaliação com métricas determinísticas e intervalos de confiança.

**Linguagem a evitar na UI e no README:** "garantia anti-alucinação", "precisão absoluta".
**Linguagem correcta:** "recusa verificada", "citações validadas automaticamente", "taxa de recusa correcta medida em N perguntas".

### Âmbito (v1)
- PDFs **com texto** (não digitalizados), até 10 MB e 30 páginas.
- Português e inglês.
- Sessão anónima (sem contas).
- Documentos de demonstração pré-indexados.

### Fora do âmbito (não implementar)
- OCR, tabelas estruturadas, reranker, multi-tenant com contas, streaming de resposta, OpenTelemetry, Kubernetes.

---

## 1. Stack e decisões

| Peça | Escolha | Nota |
|---|---|---|
| Backend | Python 3.12 + FastAPI (async) | OpenAPI gerado automaticamente |
| ORM / migrações | SQLAlchemy 2.0 async + asyncpg + Alembic | |
| Vectores | PostgreSQL + `pgvector` (Neon em produção, Docker em local) | |
| RAG | Python puro, **sem LangChain** | decisão deliberada: demonstrar domínio |
| Extracção | PyMuPDF (`fitz`) | texto + coordenadas de palavras |
| Embeddings | Gemini `gemini-embedding-001`, **768 dimensões** (Matryoshka) | normalizar vectores; configurável |
| Geração | Gemini Flash (nome em `GEN_MODEL`, **nunca fixo no código**) | verificar lista actual de modelos |
| Validação | Pydantic v2 + `pydantic-settings` | |
| Retries | `tenacity` (backoff exponencial com jitter) | |
| Rate limit | `slowapi` | |
| Logs | `structlog` (JSON) com `request_id` | |
| Erros | Sentry (plano gratuito) | |
| Ficheiros | Disco local (dev) / Cloudflare R2 privado + URLs pré-assinadas (prod) | |
| Frontend | Next.js App Router + Tailwind + shadcn/ui + `pdfjs-dist` | |
| Tipos do cliente | `openapi-typescript` gerado a partir do OpenAPI | |
| Hosting | **Render (plano gratuito)** para o backend, Vercel para o frontend, Neon, R2 | ver §10 |

### Porquê 768 dimensões
- O tipo `vector` do pgvector só indexa (HNSW/IVFFlat) até 2000 dimensões; 3072 ficaria sem índice.
- O plano gratuito da Neon tem armazenamento limitado (confirmar o limite actual): 768 dim ocupa 4× menos que 3072.
- A perda de qualidade de 3072→768 com Matryoshka é pequena para este caso, mas **deve ser medida** no benchmark (ver §8, experiência opcional).
- Ao truncar dimensões, **normalizar L2** antes de guardar.
- Guardar `embedding_model` e `embedding_dim` em cada chunk.

---

## 2. Estrutura do repositório

```
prag/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI app, lifespan (arranca o worker)
│   │   ├── config.py            # pydantic-settings
│   │   ├── api/                 # routers: documents, ask, evals, health
│   │   ├── core/                # logging, security, limits, rate limit
│   │   ├── db/                  # modelos SQLAlchemy, sessão, migrações (alembic/)
│   │   ├── ingestion/           # extract.py, chunker.py, worker.py
│   │   ├── retrieval/           # hybrid.py (SQL), embeddings.py
│   │   ├── generation/          # prompt.py, schema.py, verifier.py, pipeline.py
│   │   └── evals/               # runner.py, metrics.py, datasets/
│   ├── tests/
│   ├── scripts/                 # seed_demo.py, run_evals.py
│   ├── Dockerfile
│   └── pyproject.toml
├── frontend/                    # Next.js
├── docker-compose.yml           # Postgres+pgvector local
├── SPEC.md
├── DECISIONS.md                 # 1 linha por decisão técnica
└── README.md
```

---

## 3. Modelo de dados (PostgreSQL)

```sql
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE documents (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id    text,                          -- NULL para documentos de demo
  filename      text NOT NULL,
  sha256        text NOT NULL,
  storage_key   text NOT NULL,
  page_count    int,
  status        text NOT NULL DEFAULT 'queued',-- queued|processing|ready|failed
  error         text,
  is_demo       boolean NOT NULL DEFAULT false,
  created_at    timestamptz NOT NULL DEFAULT now(),
  UNIQUE (session_id, sha256)
);

CREATE TABLE chunks (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  document_id     uuid NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  chunk_index     int  NOT NULL,
  page_start      int  NOT NULL,
  page_end        int  NOT NULL,
  text            text NOT NULL,
  bboxes          jsonb NOT NULL,              -- [{page,x0,y0,x1,y1}, ...] em pontos PDF
  embedding       vector(768),
  embedding_model text NOT NULL,
  embedding_dim   int  NOT NULL,
  tsv             tsvector GENERATED ALWAYS AS (to_tsvector('portuguese', text)) STORED,
  UNIQUE (document_id, chunk_index)
);
CREATE INDEX chunks_embedding_hnsw ON chunks USING hnsw (embedding vector_cosine_ops);
CREATE INDEX chunks_tsv_gin        ON chunks USING gin (tsv);

CREATE TABLE ingestion_jobs (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  document_id uuid NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  status      text NOT NULL DEFAULT 'queued', -- queued|processing|done|failed
  attempts    int  NOT NULL DEFAULT 0,
  last_error  text,
  progress    int  NOT NULL DEFAULT 0,        -- páginas processadas
  updated_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE query_log (
  id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id     text,
  question       text NOT NULL,
  retrieved      jsonb NOT NULL,   -- [{chunk_id, page, vec_score, fts_rank, rrf}]
  answer         jsonb,            -- resposta estruturada final
  refused        boolean NOT NULL,
  refusal_reason text,             -- below_threshold|not_answerable|citation_verification_failed
  latency_ms     jsonb NOT NULL,   -- {embed, retrieve, generate, verify, total}
  tokens_in      int,
  tokens_out     int,
  created_at     timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE eval_questions (
  id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  document_id      uuid NOT NULL REFERENCES documents(id),
  split            text NOT NULL,              -- dev|test
  qtype            text NOT NULL,              -- answerable|unanswerable|injection
  question         text NOT NULL,
  expected_pages   int[],                      -- vazio se unanswerable/injection
  must_contain     text[]                      -- substrings esperadas na resposta
);

CREATE TABLE eval_runs (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  split       text NOT NULL,
  config      jsonb NOT NULL,   -- modelos, dim, chunk params, thresholds, hash do prompt
  summary     jsonb,            -- métricas agregadas + IC
  created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE eval_results (
  run_id          uuid REFERENCES eval_runs(id) ON DELETE CASCADE,
  question_id     uuid REFERENCES eval_questions(id),
  retrieved_pages int[],
  cited_pages     int[],
  refused         boolean,
  citation_valid  boolean,
  retrieval_hit   boolean,
  passed          boolean,
  PRIMARY KEY (run_id, question_id)
);
```

**Pesquisa híbrida (RRF, k=60)** — implementar em SQL:

```sql
WITH vec AS (
  SELECT id, row_number() OVER (ORDER BY embedding <=> :qvec) AS r
  FROM chunks WHERE document_id = ANY(:doc_ids)
  ORDER BY embedding <=> :qvec LIMIT :n
), fts AS (
  SELECT id, row_number() OVER (ORDER BY ts_rank_cd(tsv, q) DESC) AS r
  FROM chunks, websearch_to_tsquery('portuguese', :qtext) q
  WHERE document_id = ANY(:doc_ids) AND tsv @@ q
  ORDER BY ts_rank_cd(tsv, q) DESC LIMIT :n
)
SELECT c.*, COALESCE(1.0/(60+vec.r),0) + COALESCE(1.0/(60+fts.r),0) AS rrf
FROM chunks c
LEFT JOIN vec ON vec.id = c.id
LEFT JOIN fts ON fts.id = c.id
WHERE vec.id IS NOT NULL OR fts.id IS NOT NULL
ORDER BY rrf DESC LIMIT :k;
```
Guardar também a **similaridade cosseno bruta** do melhor chunk vectorial para o threshold.

> Neon usa pgbouncer: com `asyncpg`, desactivar o cache de prepared statements (`statement_cache_size=0`) e usar a connection string *pooled*.

---

## 4. Ingestão

### 4.1 Fluxo
1. `POST /documents` valida e guarda o ficheiro, cria `documents` + `ingestion_jobs`, devolve **202**.
2. Um **worker loop** arrancado no `lifespan` apanha jobs:
   ```sql
   SELECT id FROM ingestion_jobs
   WHERE status='queued' ORDER BY updated_at
   FOR UPDATE SKIP LOCKED LIMIT 1;
   ```
3. **Recuperação ao arrancar:** jobs em `processing` com `updated_at` mais antigo que 5 min voltam a `queued` (a instância gratuita hiberna e reinicia).
4. Os passos são **idempotentes**: o chunk é `UNIQUE (document_id, chunk_index)`; reprocessar não duplica.
5. Gravar progresso e `updated_at` por lote.

### 4.2 Validação de upload (`core/limits.py`)
- Máx. **10 MB** e **30 páginas**.
- Verificar *magic bytes* (`%PDF-`), não só a extensão.
- Calcular SHA-256; se já existir para a sessão, devolver o documento existente.
- Detectar PDF sem texto (média < 50 caracteres/página): `status=failed`, mensagem clara ("PDF digitalizado: OCR fora do âmbito").
- Rejeitar PDFs encriptados.

### 4.3 Extracção e chunking (`ingestion/`)
- Processar **página a página** (memória limitada a 512 MB).
- Usar `page.get_text("words")` para texto e coordenadas.
- **Remover cabeçalhos/rodapés:** linhas que se repetem em > 50% das páginas nas bandas superior/inferior (10% da altura).
- **Chunking:** alvo ~250 tokens, sobreposição ~15%, um chunk nunca abrange mais de 2 páginas; guardar `page_start`, `page_end` e `bboxes` das palavras que o compõem.
- Embeddings em lotes de tamanho fixo, com `asyncio.Semaphore(3)` e `tenacity` para 429/5xx.
- Task type: `RETRIEVAL_DOCUMENT` para chunks, `RETRIEVAL_QUERY` para perguntas.

---

## 5. Pergunta e resposta (`generation/`)

### 5.1 Fluxo de decisão
```
pergunta
  → embedding (RETRIEVAL_QUERY)
  → pesquisa híbrida (top k=8)
  → [GATE 1] melhor similaridade cosseno < THRESHOLD ? → recusa (below_threshold)
  → LLM com saída JSON estruturada
  → [GATE 2] answerable == false ? → recusa (not_answerable)
  → [GATE 3] verificar cada citação no texto do chunk
        → descartar afirmações não verificadas
        → nenhuma sobra ? → recusa (citation_verification_failed)
  → resposta + citações
```
Mensagem de recusa: *"Não encontrei esta informação nos documentos fornecidos."*

### 5.2 Esquema de saída do LLM
```json
{
  "answerable": true,
  "claims": [
    {
      "text": "O prazo de pagamento é de 30 dias.",
      "citations": [{"chunk_id": "…", "quote": "pagamento no prazo de trinta (30) dias"}]
    }
  ]
}
```
- `quote` tem de ser **cópia literal** do chunk.
- Validar com Pydantic; se o JSON for inválido, **1 retry**; se falhar de novo, erro controlado (nunca texto livre).

### 5.3 Verificador de citações (`verifier.py`) — ZONA DE RISCO, rever à mão
- Normalizar ambos os lados: minúsculas, colapsar espaços, remover hifenização de fim de linha, normalizar aspas e travessões (Unicode NFKC).
- Aceitar apenas se `quote_normalizada` for **substring** do chunk normalizado.
- Alternativa documentada em `DECISIONS.md` (se o rigor causar demasiadas recusas indevidas): `rapidfuzz.fuzz.partial_ratio >= 95`. Medir no benchmark antes de decidir.
- Testes unitários obrigatórios: hifenização, espaços duplicados, aspas curvas, quote inexistente, quote noutro chunk.

### 5.4 Prompt (mínimo)
- Papel: responder **apenas** com base nos excertos fornecidos.
- Excertos delimitados e identificados por `chunk_id`, marcados como **dados não confiáveis**: instruções dentro dos excertos devem ser ignoradas.
- Se os excertos não responderem à pergunta, `answerable=false`.
- Guardar o hash do prompt em `eval_runs.config`.

### 5.5 Resposta da API
```json
{
  "refused": false,
  "refusal_reason": null,
  "answer": "…",
  "citations": [{"claim_index":0,"document_id":"…","page":4,"quote":"…","bboxes":[…]}],
  "latency_ms": {"embed":120,"retrieve":35,"generate":900,"verify":2,"total":1070}
}
```

---

## 6. API

| Método | Rota | Descrição |
|---|---|---|
| POST | `/documents` | Upload multipart → `202 {document_id, job_id}` |
| GET | `/documents` | Lista (demo + da sessão) com `status` e progresso |
| GET | `/documents/{id}` | Detalhe |
| GET | `/documents/{id}/file` | URL pré-assinada (expira em 10 min) |
| DELETE | `/documents/{id}` | Apaga ficheiro, chunks e job |
| POST | `/ask` | `{document_ids[], question}` → resposta §5.5 |
| POST | `/evals/run` | `{split}` → `202 {run_id}` (só admin/demo; limitado) |
| GET | `/evals/runs` | Histórico |
| GET | `/evals/runs/{id}` | Resumo + resultados por pergunta |
| GET | `/health` | Liveness, **sem** tocar na BD |
| GET | `/ready` | Readiness, faz `SELECT 1` (acorda a Neon) |

Sessão anónima via cookie `session_id` (UUID, `HttpOnly`, `SameSite=None; Secure` por o frontend estar noutro domínio).
CORS com lista explícita de origens (incluir domínio de produção e *preview* do Vercel).

---

## 7. Segurança e abuso (demo público)

- Limites do §4.2 aplicados no servidor.
- `slowapi`: ex. 10 perguntas/min e 5 uploads/hora por IP.
- **Tecto diário** de chamadas ao Gemini (contador na BD); ao atingi-lo, a UI mostra "limite diário da demo atingido".
- Bucket R2 **privado**, só URLs pré-assinadas.
- Sessões só vêem os **seus** documentos e os de demo (filtrar sempre por `session_id` ou `is_demo`).
- **Prompt injection:** ver §5.4 e incluir casos no benchmark.
- Não registar o texto completo dos documentos nos logs.
- Documentos de utilizadores apagados automaticamente após 24 h (tarefa no worker).
- Aviso na UI: "Não carregues documentos confidenciais nesta demo."
- **Verificar os termos de uso de dados do plano gratuito do Gemini** antes de qualquer promessa de confidencialidade.

---

## 8. Avaliação (benchmark)

### 8.1 Dataset
- Mínimo **60 perguntas** por documento de demo, repartidas:
  - ~50% `answerable` (com `expected_pages` e `must_contain`),
  - ~35% `unanswerable` (tema próximo mas sem resposta no documento),
  - ~15% `injection` (o texto do PDF ou a pergunta tenta mudar o comportamento).
- Divisão **dev / test** (50/50). O threshold e os parâmetros calibram-se **só no dev**; o relatório final usa **só o test**.
- Documentos de demo: 2-3 PDFs fictícios ou de domínio público, criados/escolhidos por ti.

### 8.2 Métricas (todas determinísticas)
| Métrica | Definição |
|---|---|
| Recall@k de recuperação | % de `answerable` em que alguma `expected_page` está entre os chunks recuperados |
| Citação válida | % de respostas cujas citações passam o verificador |
| Cobertura de resposta | % de `answerable` cuja resposta contém todas as `must_contain` |
| Recusa correcta | % de `unanswerable` que foram recusadas |
| Recusa indevida | % de `answerable` que foram recusadas (falso negativo) |
| Resistência a injection | % de `injection` em que o sistema não obedeceu |

- Reportar sempre **n** e **intervalo de confiança de Wilson 95%**. Com poucas perguntas o intervalo é largo, e isso deve aparecer no dashboard.
- Opcional (se houver tempo): comparar 768 vs 1536 dim e híbrida vs só vectorial, numa tabela no README.

### 8.3 Reprodutibilidade
`eval_runs.config` regista: `GEN_MODEL`, `EMBED_MODEL`, dimensão, parâmetros de chunking, `k`, `THRESHOLD`, hash do prompt, commit git.

### 8.4 Calibração do threshold
Percorrer valores no split **dev**, traçar recusa correcta vs recusa indevida e escolher o ponto de equilíbrio. Documentar o gráfico em `DECISIONS.md`.

---

## 9. Frontend

- **Layout split-view:** esquerda, chat; direita, PDF.
- Clicar numa citação → `pdfjs` vai à página e desenha **sobreposição de destaque** com os `bboxes` (converter coordenadas PDF para o viewport do pdf.js; atenção à origem do eixo Y).
- `pdfjs-dist` carregado com `dynamic(..., { ssr: false })` e worker configurado explicitamente.
- Estados obrigatórios: **a iniciar o servidor (~1 min)**, a processar documento (barra de progresso via polling a `/documents`), recusa (visualmente distinta), erro, limite atingido.
- Página `/evals`: tabela de runs, métricas com IC, lista de perguntas falhadas.
- Página/painel `/stats` (a partir de `query_log`): latência por fase, taxa de recusa, custo estimado.
- Cliente da API gerado com `openapi-typescript`; sem tipos escritos à mão para respostas.
- Responsive (o PDF passa para separador no telemóvel).

---

## 10. Deploy (plano gratuito)

- **Backend:** Render (serviço web gratuito, 512 MB, hiberna após inactividade, arranque a frio de cerca de 1 min). **Um só worker `uvicorn`.** Deploy via `Dockerfile`.
- **Mitigações (obrigatórias):**
  1. Frontend chama `/ready` ao carregar e mostra o estado "a iniciar".
  2. Ping periódico externo (UptimeRobot ou cron-job.org) a `/ready` a cada ~10 min.
  3. Documentos de demo **pré-indexados** por `scripts/seed_demo.py` (o visitante pergunta logo, sem upload).
- **Neon:** usar connection string *pooled*; o ping a `/ready` acorda também a BD.
- **Variáveis de ambiente:** `DATABASE_URL`, `GEMINI_API_KEY`, `GEN_MODEL`, `EMBED_MODEL`, `EMBED_DIM`, `SIM_THRESHOLD`, `R2_*`, `ALLOWED_ORIGINS`, `SENTRY_DSN`, `DAILY_LLM_CAP`.
- Confirmar limites actuais dos planos gratuitos (Render, Neon, R2, Gemini) antes de publicar o URL.

---

## 11. Testes e CI

**Obrigatórios (`pytest` + `httpx.AsyncClient`, LLM com mock):**
- Chunker: página única, abrangência de 2 páginas, remoção de cabeçalho/rodapé, bboxes presentes.
- Verificador de citações (casos do §5.3).
- Métricas e intervalo de Wilson (valores conhecidos).
- Validação de upload (tipo falso, tamanho, páginas, PDF sem texto, duplicado).
- Recuperação de job preso em `processing`.
- Isolamento: uma sessão não consegue ler documento de outra.

**CI (GitHub Actions):** `ruff`, `mypy` (ou `pyright`), `pytest`; benchmark pequeno apenas em execução manual (consome quota).

---

## 12. Plano de implementação

| Fase | Entrega | Critério de aceitação | Rever à mão |
|---|---|---|---|
| 0 | Repo, `docker-compose`, config, Alembic, schema §3 | `alembic upgrade head` limpa; extensão pgvector activa | Schema |
| 1 | Upload + validação + storage + job | Upload devolve 202; limites rejeitam correctamente | Validação §4.2 |
| 2 | Worker, extracção, chunking, embeddings | Documento passa a `ready`; reinício a meio retoma | **Chunker e bboxes** |
| 3 | Pesquisa híbrida + `/ask` com 3 gates | Pergunta com resposta devolve citações; fora do tema recusa | **Verificador** |
| 4 | Frontend: chat + PDF + highlight | Clique na citação destaca a passagem correcta | Coordenadas |
| 5 | Dataset + runner de evals + métricas + calibração | Run guardado com config completa e ICs | **Métricas** |
| 6 | Dashboard `/evals` e `/stats`, `query_log` | Números do dashboard batem com cálculo manual | |
| 7 | Segurança: rate limit, tectos, limpeza, presigned | Testes de isolamento passam | Filtros por sessão |
| 8 | Deploy, mitigações do §10, seed demo | Visitante novo obtém resposta em < 90 s do primeiro clique | |
| 9 | README, `DECISIONS.md`, GIF | Ver §13 | |

Esforço estimado: **25-35 h**.

---

## 13. Definição de pronto e apresentação

- [ ] URL público a funcionar, com documentos de demo já indexados.
- [ ] README com: problema, GIF de 15 s (pergunta → citação → salto e destaque), tabela de resultados do benchmark **no split de teste com n e IC**, decisões técnicas e **limitações assumidas** (sem OCR, sem tabelas, limites de tamanho).
- [ ] `DECISIONS.md` com pelo menos: RAG sem framework, 768 dim, híbrida vs vectorial, verificador por substring, threshold e gráfico de calibração, hosting gratuito e mitigações.
- [ ] Testes do §11 a passar no CI.
- [ ] Nenhuma frase do README promete "zero alucinações".

---

## 14. Decisões em aberto (confirmar antes da Fase 0)

1. Nome exacto do modelo de geração actual (`GEN_MODEL`) e quota do plano gratuito.
2. Valor inicial de `SIM_THRESHOLD` (calibrar na Fase 5; começar com 0.5 como ponto de partida e ajustar).
3. Quais os 2-3 documentos de demo (fictícios ou públicos).
4. Tecto diário `DAILY_LLM_CAP`.
