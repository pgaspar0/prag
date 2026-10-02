# Regras de Desenvolvimento para Agentes (PRAG)

> **REGRA DE OURO:** O documento [`SPEC.md`](./SPEC.md) prevalece sobre qualquer skill, biblioteca externa ou sugestão padrão.
> **Uma fase = uma sessão = um commit.** Não implementes nada fora do âmbito descrito no SPEC.

## 1. Regras Inegociáveis

1. **Prevalência do SPEC.md:**
   - Não adicionar Redis, Celery, JWT/contas de utilizador, LangChain nem LlamaIndex.
   - O projeto usa **RAG Puro em Python**, fila de jobs baseada em PostgreSQL (`SELECT ... FOR UPDATE SKIP LOCKED`), e sessão anónima via cookie.
2. **Nomes de Modelos Apenas em Configuração:**
   - NUNCA colocar nomes de modelos fixos no código (`hardcoded`).
   - Usar sempre `pydantic-settings` (`config.py` com `GEN_MODEL`, `EMBED_MODEL`, `EMBED_DIM`).
3. **Isolamento de Sessão:**
   - Toda a query e operação de leitura/escrita de documentos deve filtrar estritamente por `session_id` ou permitir apenas se `is_demo = true`.
4. **Verificação Determinística de Citações (Gate 3):**
   - Uma citação gerada pelo LLM só é aceite se o excerto (`quote`) for uma **substring literal** (após normalização de espaços, minúsculas e hifenização) do texto do chunk correspondente.
   - Se falhar a verificação, a afirmação é descartada.
5. **Linguagem Factual (Zero Alucinações de Marketing):**
   - NUNCA usar na UI, README ou logs expressões como "garantia anti-alucinação" ou "precisão absoluta".
   - Usar sempre termos técnicos mensuráveis: "recusa verificada", "citações validadas automaticamente", "taxa de recusa correta medida em N perguntas".

## 2. Skills Instaladas no Repositório

As seguintes skills estão disponíveis em `.agents/skills/`:
- `pdf`: Geração e manipulação de ficheiros PDF (útil para os PDFs fictícios de teste).
- `frontend-design`: Diretrizes de UI/UX polida e intencional para Next.js/Tailwind.
- `webapp-testing`: Testes locais end-to-end com Playwright.
- `skill-creator`: Criação e otimização de skills.
- `fastapi-rag-service`: Padrões de arquitetura do backend FastAPI.
- `neon-pgvector-db`: Schema, extensões e índices HNSW no Postgres/pgvector.
- `rag-pure-pipeline`: Ingestão com PyMuPDF, embeddings Gemini e 3 gates de decisão.
- `rag-benchmark-evals`: Runner determinístico de benchmarks e cálculo do Wilson score.
- `pdf-viewer-citations`: Visualizador de PDF e salto com destaque de coordenadas.
