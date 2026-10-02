"use client";

import React, { useEffect, useState } from "react";
import {
  CheckCircle2,
  XCircle,
  AlertTriangle,
  Play,
  RotateCcw,
  ShieldCheck,
  Search,
  FileText,
  Sliders,
  Info,
  ChevronDown,
  ChevronRight,
  Sparkles,
} from "lucide-react";
import {
  BenchmarkSummary,
  EvalResultItem,
  EvalRunDetail,
  EvalRunListItem,
  getEvalRunDetail,
  getEvalRuns,
  triggerEvalRun,
} from "@/lib/api-client";
import { Navbar } from "@/components/layout/Navbar";

export default function EvalsPage() {
  const [runs, setRuns] = useState<EvalRunListItem[]>([]);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [runDetail, setRunDetail] = useState<EvalRunDetail | null>(null);
  const [loadingRuns, setLoadingRuns] = useState<boolean>(true);
  const [loadingDetail, setLoadingDetail] = useState<boolean>(false);
  const [triggering, setTriggering] = useState<boolean>(false);
  const [activeTab, setActiveTab] = useState<"all" | "answerable" | "unanswerable" | "injection">("all");
  const [filterFailedOnly, setFilterFailedOnly] = useState<boolean>(false);
  const [expandedQuestions, setExpandedQuestions] = useState<Record<string, boolean>>({});

  const loadRuns = async () => {
    try {
      setLoadingRuns(true);
      const data = await getEvalRuns(25);
      setRuns(data);
      if (data.length > 0 && !selectedRunId) {
        setSelectedRunId(data[0].id);
      }
    } catch (err) {
      console.error("Failed loading eval runs:", err);
    } finally {
      setLoadingRuns(false);
    }
  };

  const loadDetail = async (id: string) => {
    try {
      setLoadingDetail(true);
      const detail = await getEvalRunDetail(id);
      setRunDetail(detail);
    } catch (err) {
      console.error("Failed loading run detail:", err);
    } finally {
      setLoadingDetail(false);
    }
  };

  useEffect(() => {
    loadRuns();
  }, []);

  useEffect(() => {
    if (selectedRunId) {
      loadDetail(selectedRunId);
    }
  }, [selectedRunId]);

  const handleTriggerRun = async (split: "dev" | "test") => {
    try {
      setTriggering(true);
      await triggerEvalRun(split);
      // Wait 3 seconds and refresh runs list
      setTimeout(() => {
        loadRuns();
        setTriggering(false);
      }, 3500);
    } catch (err) {
      console.error("Failed triggering eval:", err);
      setTriggering(false);
    }
  };

  const toggleExpand = (qid: string) => {
    setExpandedQuestions((prev) => ({ ...prev, [qid]: !prev[qid] }));
  };

  const summary = runDetail?.summary;
  const results = runDetail?.results || [];

  const filteredResults = results.filter((item) => {
    if (activeTab !== "all" && item.qtype !== activeTab) return false;
    if (filterFailedOnly && item.passed) return false;
    return true;
  });

  return (
    <div className="flex flex-col min-h-screen bg-zinc-950 text-zinc-100 font-sans">
      <Navbar />

      <main className="flex-1 max-w-7xl w-full mx-auto p-6 md:p-8 space-y-8">
        {/* Header / Objective */}
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-zinc-800 pb-6">
          <div>
            <h1 className="text-2xl font-bold tracking-tight text-zinc-100 flex items-center gap-2">
              Scorecard de Avaliação & Benchmarks
              <span className="text-xs font-mono font-medium px-2.5 py-0.5 rounded-full bg-sky-950 border border-sky-800 text-sky-400">
                Métricas Determinísticas
              </span>
            </h1>
            <p className="text-sm text-zinc-400 mt-1 max-w-2xl">
              Medição empírica de recusa verificada e citações validadas automaticamente com intervalos de
              confiança de Wilson (95%). Critérios matemáticos estritos sem depender de LLM como juiz.
            </p>
          </div>

          <div className="flex items-center gap-2.5">
            <button
              onClick={() => handleTriggerRun("dev")}
              disabled={triggering}
              className="flex items-center gap-2 px-3.5 py-2 text-xs font-semibold rounded-lg bg-zinc-800 hover:bg-zinc-700 text-zinc-200 border border-zinc-700 transition-all disabled:opacity-50"
            >
              <Play className="w-3.5 h-3.5 text-amber-400" />
              <span>Correr Dev</span>
            </button>
            <button
              onClick={() => handleTriggerRun("test")}
              disabled={triggering}
              className="flex items-center gap-2 px-4 py-2 text-xs font-semibold rounded-lg bg-sky-600 hover:bg-sky-500 text-white shadow transition-all disabled:opacity-50"
            >
              {triggering ? (
                <RotateCcw className="w-3.5 h-3.5 animate-spin" />
              ) : (
                <Play className="w-3.5 h-3.5" />
              )}
              <span>Correr Test Split</span>
            </button>
          </div>
        </div>

        {/* Run Selector & Config Banner */}
        <div className="bg-zinc-900/60 border border-zinc-800 rounded-xl p-4 flex flex-wrap items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <Sliders className="w-4 h-4 text-sky-400" />
            <span className="text-xs font-medium text-zinc-400">Histórico de Execuções:</span>
            <select
              value={selectedRunId || ""}
              onChange={(e) => setSelectedRunId(e.target.value)}
              className="bg-zinc-800 border border-zinc-700 text-zinc-200 text-xs rounded-lg px-3 py-1.5 focus:outline-none focus:border-sky-500 font-mono"
            >
              {runs.map((r) => {
                const dateStr = new Date(r.created_at).toLocaleString("pt-PT", {
                  day: "2-digit",
                  month: "2-digit",
                  hour: "2-digit",
                  minute: "2-digit",
                });
                const passRate = r.summary
                  ? `${(r.summary.overall_pass.rate * 100).toFixed(0)}%`
                  : "pendente";
                return (
                  <option key={r.id} value={r.id}>
                    [{r.split.toUpperCase()}] {dateStr} — Sucesso: {passRate} (Commit: {r.config?.git_commit || "dev"})
                  </option>
                );
              })}
            </select>
          </div>

          {runDetail && (
            <div className="flex flex-wrap items-center gap-2 text-xs font-mono text-zinc-400">
              <span className="px-2 py-0.5 rounded bg-zinc-800 border border-zinc-700">
                Split: <strong className="text-zinc-200">{runDetail.split}</strong>
              </span>
              <span className="px-2 py-0.5 rounded bg-zinc-800 border border-zinc-700">
                Threshold: <strong className="text-zinc-200">{runDetail.config?.sim_threshold ?? "0.40"}</strong>
              </span>
              <span className="px-2 py-0.5 rounded bg-zinc-800 border border-zinc-700">
                Modelo: <strong className="text-zinc-200">{runDetail.config?.gen_model}</strong>
              </span>
              <span className="px-2 py-0.5 rounded bg-zinc-800 border border-zinc-700">
                Embeddings: <strong className="text-zinc-200">{runDetail.config?.embed_dim}d</strong>
              </span>
            </div>
          )}
        </div>

        {/* 6 Metric Cards with Wilson 95% Intervals */}
        {summary ? (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {/* 1. Recusa Correcta */}
            <div className="bg-zinc-900/70 border border-zinc-800 rounded-xl p-5 relative overflow-hidden flex flex-col justify-between">
              <div>
                <div className="flex items-center justify-between text-xs text-zinc-400 mb-2">
                  <span className="font-semibold uppercase tracking-wider text-emerald-400">
                    Recusa Correcta
                  </span>
                  <span className="font-mono text-zinc-500">n = {summary.correct_refusal.n}</span>
                </div>
                <div className="text-3xl font-extrabold text-zinc-100 font-mono tracking-tight">
                  {(summary.correct_refusal.rate * 100).toFixed(1)}%
                </div>
                <div className="text-xs font-mono text-emerald-400/90 mt-1">
                  IC 95%: [{ (summary.correct_refusal.ci_lower * 100).toFixed(1) }% —{" "}
                  { (summary.correct_refusal.ci_upper * 100).toFixed(1) }%]
                </div>
              </div>
              <p className="text-xs text-zinc-400 mt-4 leading-relaxed border-t border-zinc-800/80 pt-3">
                Percentagem de perguntas fora do documento que foram rigorosamente recusadas pelo sistema.
              </p>
            </div>

            {/* 2. Recusa Indevida */}
            <div className="bg-zinc-900/70 border border-zinc-800 rounded-xl p-5 relative overflow-hidden flex flex-col justify-between">
              <div>
                <div className="flex items-center justify-between text-xs text-zinc-400 mb-2">
                  <span className="font-semibold uppercase tracking-wider text-amber-400">
                    Recusa Indevida (Falso Negativo)
                  </span>
                  <span className="font-mono text-zinc-500">n = {summary.undue_refusal.n}</span>
                </div>
                <div className="text-3xl font-extrabold text-zinc-100 font-mono tracking-tight">
                  {(summary.undue_refusal.rate * 100).toFixed(1)}%
                </div>
                <div className="text-xs font-mono text-amber-400/90 mt-1">
                  IC 95%: [{ (summary.undue_refusal.ci_lower * 100).toFixed(1) }% —{" "}
                  { (summary.undue_refusal.ci_upper * 100).toFixed(1) }%]
                </div>
              </div>
              <p className="text-xs text-zinc-400 mt-4 leading-relaxed border-t border-zinc-800/80 pt-3">
                Perguntas que tinham resposta no documento mas foram indevidamente recusadas (quanto mais baixo, melhor).
              </p>
            </div>

            {/* 3. Citação Válida */}
            <div className="bg-zinc-900/70 border border-zinc-800 rounded-xl p-5 relative overflow-hidden flex flex-col justify-between">
              <div>
                <div className="flex items-center justify-between text-xs text-zinc-400 mb-2">
                  <span className="font-semibold uppercase tracking-wider text-sky-400">
                    Citações Válidas
                  </span>
                  <span className="font-mono text-zinc-500">n = {summary.valid_citation.n}</span>
                </div>
                <div className="text-3xl font-extrabold text-zinc-100 font-mono tracking-tight">
                  {(summary.valid_citation.rate * 100).toFixed(1)}%
                </div>
                <div className="text-xs font-mono text-sky-400/90 mt-1">
                  IC 95%: [{ (summary.valid_citation.ci_lower * 100).toFixed(1) }% —{" "}
                  { (summary.valid_citation.ci_upper * 100).toFixed(1) }%]
                </div>
              </div>
              <p className="text-xs text-zinc-400 mt-4 leading-relaxed border-t border-zinc-800/80 pt-3">
                Respostas cujos excertos citados foram confirmados como cópia literal na página do PDF.
              </p>
            </div>

            {/* 4. Recall@k de Recuperação */}
            <div className="bg-zinc-900/70 border border-zinc-800 rounded-xl p-5 relative overflow-hidden flex flex-col justify-between">
              <div>
                <div className="flex items-center justify-between text-xs text-zinc-400 mb-2">
                  <span className="font-semibold uppercase tracking-wider text-indigo-400">
                    Recall@k de Recuperação
                  </span>
                  <span className="font-mono text-zinc-500">n = {summary.recall_at_k.n}</span>
                </div>
                <div className="text-3xl font-extrabold text-zinc-100 font-mono tracking-tight">
                  {(summary.recall_at_k.rate * 100).toFixed(1)}%
                </div>
                <div className="text-xs font-mono text-indigo-400/90 mt-1">
                  IC 95%: [{ (summary.recall_at_k.ci_lower * 100).toFixed(1) }% —{" "}
                  { (summary.recall_at_k.ci_upper * 100).toFixed(1) }%]
                </div>
              </div>
              <p className="text-xs text-zinc-400 mt-4 leading-relaxed border-t border-zinc-800/80 pt-3">
                Frequência com que a página que contém a resposta surge entre os chunks recuperados por RRF.
              </p>
            </div>

            {/* 5. Resistência a Injection */}
            <div className="bg-zinc-900/70 border border-zinc-800 rounded-xl p-5 relative overflow-hidden flex flex-col justify-between">
              <div>
                <div className="flex items-center justify-between text-xs text-zinc-400 mb-2">
                  <span className="font-semibold uppercase tracking-wider text-rose-400">
                    Resistência a Injection
                  </span>
                  <span className="font-mono text-zinc-500">n = {summary.injection_resistance.n}</span>
                </div>
                <div className="text-3xl font-extrabold text-zinc-100 font-mono tracking-tight">
                  {(summary.injection_resistance.rate * 100).toFixed(1)}%
                </div>
                <div className="text-xs font-mono text-rose-400/90 mt-1">
                  IC 95%: [{ (summary.injection_resistance.ci_lower * 100).toFixed(1) }% —{" "}
                  { (summary.injection_resistance.ci_upper * 100).toFixed(1) }%]
                </div>
              </div>
              <p className="text-xs text-zinc-400 mt-4 leading-relaxed border-t border-zinc-800/80 pt-3">
                Tentativas adversariais de injeção de prompt ou alteração de regras neutralizadas pelo sistema.
              </p>
            </div>

            {/* 6. Cobertura de Resposta */}
            <div className="bg-zinc-900/70 border border-zinc-800 rounded-xl p-5 relative overflow-hidden flex flex-col justify-between">
              <div>
                <div className="flex items-center justify-between text-xs text-zinc-400 mb-2">
                  <span className="font-semibold uppercase tracking-wider text-teal-400">
                    Cobertura Factual (Must Contain)
                  </span>
                  <span className="font-mono text-zinc-500">n = {summary.answer_coverage.n}</span>
                </div>
                <div className="text-3xl font-extrabold text-zinc-100 font-mono tracking-tight">
                  {(summary.answer_coverage.rate * 100).toFixed(1)}%
                </div>
                <div className="text-xs font-mono text-teal-400/90 mt-1">
                  IC 95%: [{ (summary.answer_coverage.ci_lower * 100).toFixed(1) }% —{" "}
                  { (summary.answer_coverage.ci_upper * 100).toFixed(1) }%]
                </div>
              </div>
              <p className="text-xs text-zinc-400 mt-4 leading-relaxed border-t border-zinc-800/80 pt-3">
                Respostas geradas que contêm todas as entidades e termos factuais obrigatórios do gabarito.
              </p>
            </div>
          </div>
        ) : (
          <div className="bg-zinc-900/40 border border-zinc-800 rounded-xl p-12 text-center text-zinc-400">
            {loadingDetail ? "A carregar resultados do benchmark..." : "Nenhum benchmark selecionado."}
          </div>
        )}

        {/* Detailed Questions Table */}
        <div className="bg-zinc-900/60 border border-zinc-800 rounded-xl overflow-hidden">
          <div className="p-4 border-b border-zinc-800 flex flex-wrap items-center justify-between gap-3">
            <div className="flex items-center gap-2">
              <h2 className="text-sm font-bold text-zinc-200">
                Auditoria de Questões ({filteredResults.length} de {results.length})
              </h2>
            </div>

            <div className="flex items-center gap-3">
              {/* Type Filter Buttons */}
              <div className="flex bg-zinc-800 p-0.5 rounded-lg border border-zinc-700 text-xs">
                {(["all", "answerable", "unanswerable", "injection"] as const).map((tab) => (
                  <button
                    key={tab}
                    onClick={() => setActiveTab(tab)}
                    className={`px-2.5 py-1 rounded-md font-medium transition-all ${
                      activeTab === tab
                        ? "bg-zinc-900 text-sky-400 shadow-sm"
                        : "text-zinc-400 hover:text-zinc-200"
                    }`}
                  >
                    {tab === "all" ? "Todas" : tab === "answerable" ? "Respondíveis" : tab === "unanswerable" ? "Recusas" : "Injections"}
                  </button>
                ))}
              </div>

              {/* Failed Only Toggle */}
              <label className="flex items-center gap-1.5 text-xs text-zinc-400 cursor-pointer select-none">
                <input
                  type="checkbox"
                  checked={filterFailedOnly}
                  onChange={(e) => setFilterFailedOnly(e.target.checked)}
                  className="rounded border-zinc-700 bg-zinc-800 text-sky-600 focus:ring-0"
                />
                <span>Apenas falhas</span>
              </label>
            </div>
          </div>

          <div className="divide-y divide-zinc-800">
            {filteredResults.map((item) => {
              const isExpanded = !!expandedQuestions[item.question_id];
              return (
                <div key={item.question_id} className="p-4 hover:bg-zinc-900/40 transition-colors">
                  <div
                    onClick={() => toggleExpand(item.question_id)}
                    className="flex items-start justify-between gap-3 cursor-pointer"
                  >
                    <div className="flex items-start gap-3">
                      <span className="mt-0.5">
                        {item.passed ? (
                          <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0" />
                        ) : (
                          <XCircle className="w-4 h-4 text-rose-400 shrink-0" />
                        )}
                      </span>
                      <div>
                        <div className="text-sm font-medium text-zinc-200 flex items-center gap-2">
                          <span>{item.question}</span>
                          <span
                            className={`text-[10px] font-mono px-2 py-0.5 rounded-full border ${
                              item.qtype === "answerable"
                                ? "bg-sky-950/60 border-sky-800/80 text-sky-400"
                                : item.qtype === "unanswerable"
                                ? "bg-amber-950/60 border-amber-800/80 text-amber-400"
                                : "bg-rose-950/60 border-rose-800/80 text-rose-400"
                            }`}
                          >
                            {item.qtype}
                          </span>
                        </div>
                        <div className="text-xs text-zinc-400 flex flex-wrap items-center gap-3 mt-1.5">
                          {item.expected_pages && (
                            <span>
                              Páginas Esperadas:{" "}
                              <strong className="text-zinc-300 font-mono">
                                {item.expected_pages.join(", ")}
                              </strong>
                            </span>
                          )}
                          {item.cited_pages && item.cited_pages.length > 0 && (
                            <span>
                              Páginas Citadas:{" "}
                              <strong className="text-zinc-300 font-mono">
                                {item.cited_pages.join(", ")}
                              </strong>
                            </span>
                          )}
                          <span>
                            Recusado:{" "}
                            <strong className={item.refused ? "text-amber-400" : "text-emerald-400"}>
                              {item.refused ? "Sim" : "Não"}
                            </strong>
                          </span>
                        </div>
                      </div>
                    </div>

                    <button className="text-zinc-500 hover:text-zinc-300 p-1">
                      {isExpanded ? (
                        <ChevronDown className="w-4 h-4" />
                      ) : (
                        <ChevronRight className="w-4 h-4" />
                      )}
                    </button>
                  </div>

                  {isExpanded && (
                    <div className="mt-4 pl-7 text-xs space-y-2 border-t border-zinc-800/60 pt-3 text-zinc-400">
                      {item.must_contain && item.must_contain.length > 0 && (
                        <div>
                          <span className="text-zinc-500">Termos obrigatórios no gabarito:</span>{" "}
                          <span className="font-mono text-zinc-300">
                            {JSON.stringify(item.must_contain)}
                          </span>
                        </div>
                      )}
                      <div>
                        <span className="text-zinc-500">Recuperação (Hit):</span>{" "}
                        <span className="font-mono text-zinc-300">
                          {item.retrieval_hit === null ? "N/A" : item.retrieval_hit ? "Sim" : "Não"}
                        </span>
                      </div>
                      <div>
                        <span className="text-zinc-500">Citação Verificada:</span>{" "}
                        <span className="font-mono text-zinc-300">
                          {item.citation_valid === null ? "N/A" : item.citation_valid ? "Válida" : "Rejeitada"}
                        </span>
                      </div>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      </main>
    </div>
  );
}
