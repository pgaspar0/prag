# Registos de Decisão Técnica (ADR) — PRAG

| Data | Decisão | Contexto & Racional |
| :--- | :--- | :--- |
| 2026-10-02 | **RAG sem frameworks (Vanilla Python)** | Evitar a opacidade e o overhead de abstrações como LangChain/LlamaIndex; demonstrar controlo total do pipeline e dos 3 gates de decisão. |
| 2026-10-02 | **Embeddings truncados para 768 dimensões com normalização L2** | O pgvector só suporta índices HNSW até 2000 dimensões (o modelo padrão produz 3072); Matryoshka para 768 poupa 4x espaço no Neon e permite indexação HNSW. |
| 2026-10-02 | **Fila de tarefas via PostgreSQL (`SKIP LOCKED`)** | Elimina a necessidade de gerir Redis/Celery no plano gratuito do Render; recuperação automática de jobs após reinício. |
| 2026-10-02 | **Verificação determinística de citações por substring match** | A semelhança vetorial e a autoavaliação por LLM falham em garantir veracidade; a verificação exata por string match na página anotada é uma garantia matemática verificável. |
| 2026-10-02 | **Pesquisa Híbrida via RRF em SQL** | Combina precisão léxica (`tsvector` em português para datas, cláusulas e números exatos) com proximidade semântica de vetores. |
| 2026-10-02 | **Hospedagem Render + Mitigações para cold start** | Backend em plano gratuito do Render requer mitigação ativa: endpoint `/ready` para aquecimento, documentos demo pré-indexados e jobs idempotentes. |
