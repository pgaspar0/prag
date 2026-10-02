# Registos de Decisão de Arquitetura (ADR) — PRAG

Este documento regista as decisões técnicas fundamentais tomadas durante o desenho e implementação do **PRAG** (Precise RAG with Citations & Benchmarks), os seus contextos, alternativas ponderadas e trade-offs assumidos.

---

## Índice de Decisões

| ADR | Data | Decisão | Estado |
| :--- | :--- | :--- | :--- |
| **ADR-001** | 2026-10-02 | [RAG sem frameworks (Vanilla Python & FastAPI)](#adr-001-rag-sem-frameworks-vanilla-python--fastapi) | Aceite |
| **ADR-002** | 2026-10-02 | [Embeddings truncados a 768d com normalização L2 (Matryoshka)](#adr-002-embeddings-truncados-a-768d-com-normalização-l2-matryoshka) | Aceite |
| **ADR-003** | 2026-10-02 | [Fila assíncrona no PostgreSQL com `SKIP LOCKED`](#adr-003-fila-assíncrona-no-postgresql-com-skip-locked) | Aceite |
| **ADR-004** | 2026-10-02 | [Pipeline de 3 Gates e Verificador Determinístico de Citações](#adr-004-pipeline-de-3-gates-e-verificador-determinístico-de-citações) | Aceite |
| **ADR-005** | 2026-10-02 | [Pesquisa Híbrida via Reciprocal Rank Fusion (RRF) em SQL](#adr-005-pesquisa-híbrida-via-reciprocal-rank-fusion-rrf-em-sql) | Aceite |
| **ADR-006** | 2026-10-02 | [Calibração de Threshold e Intervalos de Confiança de Wilson (95%)](#adr-006-calibração-de-threshold-e-intervalos-de-confiança-de-wilson-95) | Aceite |
| **ADR-007** | 2026-10-02 | [Isolamento de Sessão, Rate Limiting (SlowAPI) e Teto Diário LLM](#adr-007-isolamento-de-sessão-rate-limiting-slowapi-e-teto-diário-llm) | Aceite |
| **ADR-008** | 2026-10-02 | [Bucket Cloudflare R2 Privado com URLs Pré-assinadas Temporárias](#adr-008-bucket-cloudflare-r2-privado-com-urls-pré-assinadas-temporárias) | Aceite |
| **ADR-009** | 2026-10-02 | [Limpeza Automática de Documentos de Sessão após 24 Horas](#adr-009-limpeza-automática-de-documentos-de-sessão-após-24-horas) | Aceite |
| **ADR-010** | 2026-10-02 | [Transparência Metodológica: Rejeição de "Zero Alucinações"](#adr-010-transparência-metodológica-rejeição-de-zero-alucinações) | Aceite |

---

### ADR-001: RAG sem frameworks (Vanilla Python & FastAPI)
* **Contexto:** Frameworks populares como LangChain ou LlamaIndex adicionam camadas excessivas de abstração, dependências pesadas e tornam o fluxo de execução opaco.
* **Decisão:** Implementar toda a lógica do RAG diretamente em Python puro, SQLAlchemy 2.0 (async), Pydantic v2 e FastAPI.
* **Consequências:** 
  - *Positivas:* Controlo milimétrico sobre cada fase (cálculo de similaridade, junção híbrida, normalização de strings, sanitização de logs).
  - *Trade-off:* Exige codificação manual da formatação de prompts e parsing estruturado via JSON Schema.

---

### ADR-002: Embeddings truncados a 768d com normalização L2 (Matryoshka)
* **Contexto:** O modelo `gemini-embedding-001` produz vetores nativos de 3072 dimensões. No entanto, os índices HNSW e IVFFlat do `pgvector` têm um limite máximo de 2000 dimensões para indexação vetorial indexada.
* **Decisão:** Truncar as dimensões do embedding para **768 dimensões** através da técnica Matryoshka e aplicar obrigatoriamente **normalização euclidiana L2** ($v / \|v\|_2$).
* **Consequências:**
  - *Positivas:* Permite criar índices `HNSW` em PostgreSQL; reduz em 4x o consumo de RAM e storage (essencial para planos gratuitos Neon/Postgres).
  - *Trade-off:* Pequena perda de resolução semântica marginal, compensada pela junção com pesquisa léxica (FTS).

---

### ADR-003: Fila assíncrona no PostgreSQL com `SKIP LOCKED`
* **Contexto:** O upload de PDFs requer extração de texto, chunking e chamadas à API de embeddings, operações que excedem o tempo limite de um request HTTP síncrono. Adicionar Redis ou Celery aumentaria a complexidade e custos de infraestrutura.
* **Decisão:** Implementar a fila de ingestão diretamente na base de dados (`ingestion_jobs`) consumida por um worker loop em background com a query:
  ```sql
  SELECT id FROM ingestion_jobs WHERE status = 'queued' ORDER BY updated_at FOR UPDATE SKIP LOCKED LIMIT 1;
  ```
  Complementado por rotina de recuperação (`recover_stale_jobs`) que resgata jobs em `processing` há mais de 5 minutos (mitigando hibernação de dynos gratuitos).
* **Consequências:**
  - *Positivas:* Zero serviços externos adicionais; consistência transacional e idempotência total.

---

### ADR-004: Pipeline de 3 Gates e Verificador Determinístico de Citações
* **Contexto:** LLMs tendem a inventar factos ou gerar citações plausíveis mas inexistentes no texto original ("alucinação de autoridade"). Avaliar o output com outro LLM ("LLM-as-a-judge") é caro, estocástico e falível.
* **Decisão:** Criar um pipeline determinístico de 3 barreiras inegociáveis:
  1. **Gate 1:** Corte de similaridade cosseno (`SIM_THRESHOLD = 0.40`). Se o excerto mais próximo estiver abaixo do corte, recusa de imediato sem gastar tokens de geração.
  2. **Gate 2:** O LLM devolve um objeto JSON estruturado (`answerable: bool`, `claims: List[Claim]`). Se classificar como não respondível ou omitir citações, recusa padronizada.
  3. **Gate 3 (Verificador Determinístico):** Cada citação textual (`quote`) é normalizada (Unicode NFKC, remoção de quebras de linha e hífens) e procurada literalmente por substring match no texto da página anotada. Se a citação falhar, a claim é descartada; se nenhuma claim for válida, o sistema emite recusa total.
* **Consequências:**
  - *Positivas:* Elimina citações fraudulentas. Toda a afirmação apresentada com link no PDF é garantidamente uma cópia exata do documento original.

---

### ADR-005: Pesquisa Híbrida via Reciprocal Rank Fusion (RRF) em SQL
* **Contexto:** A pesquisa vetorial é excelente para sinónimos e proximidade conceptual, mas falha frequentemente em termos exatos como números de cláusulas ("Cláusula 5.ª"), valores monetários ("4.500 EUR"), prazos ("15 minutos") ou siglas jurídicas.
* **Decisão:** Executar numa única query SQL uma pesquisa híbrida combinando:
  - Busca vetorial com `pgvector` (`<=>` distância cosseno com índice HNSW);
  - Busca de texto integral (Full Text Search) com dicionário `'portuguese'` e `ts_rank_cd`;
  - Fusão de classificações com RRF: $\text{score} = \frac{1}{60 + r_{vec}} + \frac{1}{60 + r_{fts}}$.
* **Consequências:**
  - *Positivas:* Resposta precisa a perguntas com termos técnicos ou códigos contratuais específicos.

---

### ADR-006: Calibração de Threshold e Intervalos de Confiança de Wilson (95%)
* **Contexto:** A escolha do threshold de similaridade define o equilíbrio entre aceitar alucinações (falso positivo) e recusar perguntas legítimas (falso negativo). Relatórios com taxas pontuais simples (ex: "85%") ocultam o tamanho da amostra e a incerteza estatística.
* **Decisão:** 
  1. Isolar a calibração de threshold exclusivamente no split **dev** (30 perguntas), percorrendo valores de 0.40 a 0.80.
  2. Avaliar o split final **test** (30 perguntas) fixando o threshold ótimo calibrado em `0.40`.
  3. Reportar **todas** as métricas com o **Intervalo de Confiança de Wilson a 95%**, matematicamente delimitado em $[0.0, 1.0]$.
* **Tabela Empírica de Calibração (Split Dev):**

| Threshold | Recusa Correcta (Wilson 95%) | Recusa Indevida (Wilson 95%) | Taxa Global (Wilson 95%) | Decisão |
| :--- | :--- | :--- | :--- | :--- |
| **0.40** | **100.0% [74.1% - 100.0%]** | **26.7% [10.9% - 52.0%]** | **83.3% [66.4% - 92.7%]** | **Ponto de equilíbrio ótimo selecionado** |
| 0.45 | 100.0% [74.1% - 100.0%] | 46.7% [24.8% - 69.9%] | 73.3% [55.6% - 85.8%] | Penalização severa de falsos negativos em perguntas legítimas |
| 0.50 | 100.0% [74.1% - 100.0%] | 86.7% [62.1% - 96.3%] | 56.7% [39.2% - 72.6%] | Demasiado restritivo para embeddings truncados a 768d |
| 0.55 | 100.0% [74.1% - 100.0%] | 86.7% [62.1% - 96.3%] | 56.7% [39.2% - 72.6%] | Ponto inicial conservador |
| 0.60+ | 100.0% [74.1% - 100.0%] | 100.0% [79.6% - 100.0%] | 50.0% [33.2% - 66.8%] | Rejeição indiscriminada |

---

### ADR-007: Isolamento de Sessão, Rate Limiting (SlowAPI) e Teto Diário LLM
* **Contexto:** Uma demonstração pública aberta à Internet corre risco de abuso, consumo descontrolado de quotas e ataques por injeção adversarial.
* **Decisão:**
  - Rate limiting via `slowapi`: máx. **10 perguntas/minuto** e **5 uploads/hora** por endereço IP.
  - Teto diário (`DAILY_LLM_CAP = 400`): tabela `daily_usage` incrementada atomicamente em cada chamada ao Gemini; ao atingir o teto, a API devolve HTTP 429 com aviso amigável.
  - Isolamento estrito: utilizadores anónimos recebem cookie `session_id` (UUIDv4) e apenas acedem aos seus próprios documentos ou a documentos públicos de demonstração (`is_demo = true`).
  - Defesa contra Prompt Injection: prompt de sistema blindado com delimitadores XML rígidos e casos de teste adversariais no benchmark.

---

### ADR-008: Bucket Cloudflare R2 Privado com URLs Pré-assinadas Temporárias
* **Contexto:** PDFs corporativos contêm propriedade intelectual ou dados sensíveis e nunca devem ser expostos em buckets abertos ou URLs permanentes.
* **Decisão:** Armazenar PDFs no Cloudflare R2 configurado como bucket estritamente privado. Acesso através de URLs pré-assinadas temporárias (validade de 10 minutos) geradas pelo endpoint `/documents/{id}/file` com `HTTP 307 Temporary Redirect` (com fallback transparente para armazenamento local em ambiente de desenvolvimento).
* **Consequências:** Proteção contra hotlinking e raspagem desautorizada de documentos.

---

### ADR-009: Limpeza Automática de Documentos de Sessão após 24 Horas
* **Contexto:** Numa demonstração temporária, ficheiros PDF carregados por visitantes e os respetivos embeddings acumulam custos de armazenamento desnecessários.
* **Decisão:** Implementar rotina periódica no worker (`cleanup_expired_documents`) executada a cada hora, que elimina em cascata ficheiros físicos (local e R2), chunks e metadados de documentos de sessão com mais de 24 horas (`is_demo = false`). Documentos de demo são preservados permanentemente.

---

### ADR-010: Transparência Metodológica: Rejeição de "Zero Alucinações"
* **Contexto:** Alegações de "zero alucinações" ou "precisão a 100%" são falsas em sistemas baseados em inteligência artificial generativa e desacreditam projetos de engenharia sénior.
* **Decisão:** Proibir formalmente a utilização de termos enganosos na interface, documentação e commits. Em sua substituição, adotar uma terminologia baseada em verificação formal:
  - Em vez de "zero alucinações", utilizar **"recusa verificada"** ou **"mecanismo determinístico de anti-alucinação"**.
  - Em vez de "precisão absoluta", reportar **"citações auditadas por correspondência literal de substring"**.
  - Assumir abertamente as limitações técnicas (sem suporte a OCR de documentos digitalizados, limite de 30 páginas e tabelas semânticas complexas fora de âmbito).
