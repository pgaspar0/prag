# Registos de Decisão Técnica (ADR) — PRAG

| Data | Decisão | Contexto & Racional |
| :--- | :--- | :--- |
| 2026-10-02 | **RAG sem frameworks (Vanilla Python)** | Evitar a opacidade e o overhead de abstrações como LangChain/LlamaIndex; demonstrar controlo total do pipeline e dos 3 gates de decisão. |
| 2026-10-02 | **Embeddings truncados para 768 dimensões com normalização L2** | O pgvector só suporta índices HNSW até 2000 dimensões (o modelo padrão produz 3072); Matryoshka para 768 poupa 4x espaço no Neon e permite indexação HNSW. |
| 2026-10-02 | **Fila de tarefas via PostgreSQL (`SKIP LOCKED`)** | Elimina a necessidade de gerir Redis/Celery no plano gratuito do Render; recuperação automática de jobs após reinício. |
| 2026-10-02 | **Verificação determinística de citações por substring match** | A semelhança vetorial e a autoavaliação por LLM falham em garantir veracidade; a verificação exata por string match na página anotada é uma garantia matemática verificável. |
| 2026-10-02 | **Pesquisa Híbrida via RRF em SQL** | Combina precisão léxica (`tsvector` em português para datas, cláusulas e números exatos) com proximidade semântica de vetores. |
| 2026-10-02 | **Hospedagem Render + Mitigações para cold start** | Backend em plano gratuito do Render requer mitigação ativa: endpoint `/ready` para aquecimento, documentos demo pré-indexados e jobs idempotentes. |
| 2026-10-02 | **Calibração de Threshold e Intervalo de Wilson 95%** | Calibração de corte cosseno isolada no split `dev` (0.40 a 0.80) para equilibrar recusa correcta vs. recusa indevida; reporte estatístico com intervalos de Wilson 95% obrigatório em todas as métricas. |

---

## Calibração Empírica do Threshold de Similaridade Cosseno (§8.4)

A calibração do Gate 1 (corte de similaridade cosseno) foi executada exclusivamente sobre o split **dev** (30 perguntas: 15 `answerable`, 11 `unanswerable`, 4 `injection`).

### Tabela de Trade-off (Split Dev)

| Threshold | Recusa Correcta (Wilson 95%) | Recusa Indevida (Wilson 95%) | Taxa Global (Wilson 95%) | Avaliação |
| :--- | :--- | :--- | :--- | :--- |
| **0.40** | **100.0% [74.1% - 100.0%]** | **26.7% [10.9% - 52.0%]** | **83.3% [66.4% - 92.7%]** | **Ponto de equilíbrio ótimo** (recusa perfeita de perguntas sem resposta e ataques adversariais) |
| 0.45 | 100.0% [74.1% - 100.0%] | 46.7% [24.8% - 69.9%] | 73.3% [55.6% - 85.8%] | Penalização severa de falsos negativos em perguntas legítimas |
| 0.50 | 100.0% [74.1% - 100.0%] | 86.7% [62.1% - 96.3%] | 56.7% [39.2% - 72.6%] | Demasiado restritivo com embeddings truncados a 768d |
| 0.55 | 100.0% [74.1% - 100.0%] | 86.7% [62.1% - 96.3%] | 56.7% [39.2% - 72.6%] | Ponto inicial conservador |
| 0.60+ | 100.0% [74.1% - 100.0%] | 100.0% [79.6% - 100.0%] | 50.0% [33.2% - 66.8%] | Rejeição indiscriminada |

### Conclusão e Ponto de Equilíbrio
1. O corte ótimo situa-se em `0.40`, onde a **recusa correcta é de 100.0%** e a taxa global de acerto no split `dev` atinge **83.3%**.
2. Valores acima de `0.45` aumentam drasticamente a **recusa indevida** (falsos negativos), bloqueando perguntas respondíveis antes de chegarem ao LLM (Gate 2).
3. Todas as métricas finais do benchmark são avaliadas estritamente no conjunto independente **test** (30 perguntas), mantendo a integridade metodológica sem overfitting aos dados de calibração.

