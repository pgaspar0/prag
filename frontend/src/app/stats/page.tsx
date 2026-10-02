"use client";

import React, { useEffect, useState } from "react";
import {
  Activity,
  Zap,
  ShieldAlert,
  Clock,
  Coins,
  TrendingDown,
  RefreshCw,
  Server,
  Layers,
  Database,
  Cpu,
  CheckCircle,
} from "lucide-react";
import { getSystemStats, SystemStatsResponse } from "@/lib/api-client";
import { Navbar } from "@/components/layout/Navbar";

export default function StatsPage() {
  const [stats, setStats] = useState<SystemStatsResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [autoRefresh, setAutoRefresh] = useState<boolean>(true);

  const fetchStats = async () => {
    try {
      const data = await getSystemStats();
      setStats(data);
    } catch (err) {
      console.error("Failed loading system stats:", err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchStats();
    if (!autoRefresh) return;
    const interval = setInterval(fetchStats, 10000);
    return () => clearInterval(interval);
  }, [autoRefresh]);

  const lat = stats?.latencies;
  const ref = stats?.refusals;
  const tc = stats?.token_cost;

  // Max latency for relative bar representation
  const maxLat = Math.max(
    lat?.embed_ms || 1,
    lat?.retrieve_ms || 1,
    lat?.generate_ms || 1,
    lat?.verify_ms || 1
  );

  return (
    <div className="flex flex-col min-h-screen bg-zinc-950 text-zinc-100 font-sans">
      <Navbar />

      <main className="flex-1 max-w-7xl w-full mx-auto p-6 md:p-8 space-y-8">
        {/* Header */}
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-zinc-800 pb-6">
          <div>
            <h1 className="text-2xl font-bold tracking-tight text-zinc-100 flex items-center gap-2">
              Observabilidade & Métricas do Sistema
              <span className="text-xs font-mono font-medium px-2.5 py-0.5 rounded-full bg-emerald-950 border border-emerald-800 text-emerald-400">
                Tempo Quase-Real
              </span>
            </h1>
            <p className="text-sm text-zinc-400 mt-1 max-w-2xl">
              Análise operacional agregada a partir da tabela <code className="font-mono text-zinc-300">query_log</code>: latências decompostas por fase dos 3 gates, taxa de recusa e economia de tokens.
            </p>
          </div>

          <div className="flex items-center gap-3">
            <button
              onClick={() => fetchStats()}
              className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg bg-zinc-800 hover:bg-zinc-700 text-zinc-200 border border-zinc-700 transition-all"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${loading ? "animate-spin" : ""}`} />
              <span>Atualizar</span>
            </button>
            <label className="flex items-center gap-1.5 text-xs text-zinc-400 select-none cursor-pointer">
              <input
                type="checkbox"
                checked={autoRefresh}
                onChange={(e) => setAutoRefresh(e.target.checked)}
                className="rounded border-zinc-700 bg-zinc-800 text-sky-600 focus:ring-0"
              />
              <span>Auto-refresh (10s)</span>
            </label>
          </div>
        </div>

        {/* Top 4 KPI Cards */}
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          {/* Total Queries */}
          <div className="bg-zinc-900/70 border border-zinc-800 rounded-xl p-5">
            <div className="flex items-center justify-between text-xs text-zinc-400 mb-2">
              <span className="font-semibold uppercase tracking-wider text-sky-400">
                Consultas Totais
              </span>
              <Activity className="w-4 h-4 text-sky-400" />
            </div>
            <div className="text-3xl font-extrabold text-zinc-100 font-mono tracking-tight">
              {stats?.total_queries ?? 0}
            </div>
            <div className="text-xs text-zinc-500 mt-1">
              {ref?.total_answered ?? 0} respondidas / {ref?.total_refused ?? 0} recusadas
            </div>
          </div>

          {/* Taxa de Recusa */}
          <div className="bg-zinc-900/70 border border-zinc-800 rounded-xl p-5">
            <div className="flex items-center justify-between text-xs text-zinc-400 mb-2">
              <span className="font-semibold uppercase tracking-wider text-amber-400">
                Taxa de Recusa
              </span>
              <ShieldAlert className="w-4 h-4 text-amber-400" />
            </div>
            <div className="text-3xl font-extrabold text-zinc-100 font-mono tracking-tight">
              {stats ? `${(stats.refusals.refusal_rate * 100).toFixed(1)}%` : "0.0%"}
            </div>
            <div className="text-xs text-zinc-500 mt-1">
              Filtro ativo de alucinações (3 gates)
            </div>
          </div>

          {/* Latência p50 / p95 */}
          <div className="bg-zinc-900/70 border border-zinc-800 rounded-xl p-5">
            <div className="flex items-center justify-between text-xs text-zinc-400 mb-2">
              <span className="font-semibold uppercase tracking-wider text-indigo-400">
                Latência Média
              </span>
              <Clock className="w-4 h-4 text-indigo-400" />
            </div>
            <div className="text-3xl font-extrabold text-zinc-100 font-mono tracking-tight">
              {lat ? `${lat.total_ms.toFixed(0)} ms` : "0 ms"}
            </div>
            <div className="text-xs font-mono text-zinc-500 mt-1">
              p50: {lat?.p50_total_ms.toFixed(0)} ms / p95: {lat?.p95_total_ms.toFixed(0)} ms
            </div>
          </div>

          {/* Tokens Poupados por Recusa Antecipada */}
          <div className="bg-zinc-900/70 border border-zinc-800 rounded-xl p-5">
            <div className="flex items-center justify-between text-xs text-zinc-400 mb-2">
              <span className="font-semibold uppercase tracking-wider text-emerald-400">
                Poupança Gate 1
              </span>
              <TrendingDown className="w-4 h-4 text-emerald-400" />
            </div>
            <div className="text-3xl font-extrabold text-zinc-100 font-mono tracking-tight">
              {tc ? `${(tc.tokens_saved_by_early_refusal / 1000).toFixed(1)}k` : "0k"}
            </div>
            <div className="text-xs text-emerald-400/90 font-mono mt-1">
              Tokens economizados (~${tc?.estimated_savings_usd.toFixed(4) || "0.00"})
            </div>
          </div>
        </div>

        {/* Latency by Phase Breakdown & Refusal Reason Distribution */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {/* Phase Latencies */}
          <div className="bg-zinc-900/60 border border-zinc-800 rounded-xl p-6 space-y-4">
            <div className="flex items-center justify-between border-b border-zinc-800 pb-3">
              <h3 className="text-sm font-bold text-zinc-200 flex items-center gap-2">
                <Cpu className="w-4 h-4 text-sky-400" />
                <span>Decomposição de Latência por Fase</span>
              </h3>
              <span className="text-xs text-zinc-500 font-mono">Médias recentes</span>
            </div>

            <div className="space-y-4 pt-2">
              {/* Embed */}
              <div>
                <div className="flex justify-between text-xs font-mono mb-1">
                  <span className="text-zinc-400">1. Vector Embedding (Matryoshka 768d)</span>
                  <span className="text-zinc-200 font-bold">{lat?.embed_ms ?? 0} ms</span>
                </div>
                <div className="w-full bg-zinc-800 h-2 rounded-full overflow-hidden">
                  <div
                    className="bg-sky-500 h-full rounded-full transition-all duration-500"
                    style={{
                      width: `${Math.min(100, ((lat?.embed_ms || 0) / maxLat) * 100)}%`,
                    }}
                  />
                </div>
              </div>

              {/* Retrieve */}
              <div>
                <div className="flex justify-between text-xs font-mono mb-1">
                  <span className="text-zinc-400">2. Hybrid Search (RRF SQL + HNSW)</span>
                  <span className="text-zinc-200 font-bold">{lat?.retrieve_ms ?? 0} ms</span>
                </div>
                <div className="w-full bg-zinc-800 h-2 rounded-full overflow-hidden">
                  <div
                    className="bg-indigo-500 h-full rounded-full transition-all duration-500"
                    style={{
                      width: `${Math.min(100, ((lat?.retrieve_ms || 0) / maxLat) * 100)}%`,
                    }}
                  />
                </div>
              </div>

              {/* Generate */}
              <div>
                <div className="flex justify-between text-xs font-mono mb-1">
                  <span className="text-zinc-400">3. LLM Generation (Flash Structured JSON)</span>
                  <span className="text-zinc-200 font-bold">{lat?.generate_ms ?? 0} ms</span>
                </div>
                <div className="w-full bg-zinc-800 h-2 rounded-full overflow-hidden">
                  <div
                    className="bg-amber-500 h-full rounded-full transition-all duration-500"
                    style={{
                      width: `${Math.min(100, ((lat?.generate_ms || 0) / maxLat) * 100)}%`,
                    }}
                  />
                </div>
              </div>

              {/* Verify */}
              <div>
                <div className="flex justify-between text-xs font-mono mb-1">
                  <span className="text-zinc-400">4. Deterministic Verification (String Match)</span>
                  <span className="text-zinc-200 font-bold">{lat?.verify_ms ?? 0} ms</span>
                </div>
                <div className="w-full bg-zinc-800 h-2 rounded-full overflow-hidden">
                  <div
                    className="bg-emerald-500 h-full rounded-full transition-all duration-500"
                    style={{
                      width: `${Math.min(100, ((lat?.verify_ms || 0) / maxLat) * 100)}%`,
                    }}
                  />
                </div>
              </div>
            </div>
          </div>

          {/* Refusal Reasons Distribution */}
          <div className="bg-zinc-900/60 border border-zinc-800 rounded-xl p-6 space-y-4">
            <div className="flex items-center justify-between border-b border-zinc-800 pb-3">
              <h3 className="text-sm font-bold text-zinc-200 flex items-center gap-2">
                <ShieldAlert className="w-4 h-4 text-amber-400" />
                <span>Distribuição de Motivos de Recusa</span>
              </h3>
              <span className="text-xs text-zinc-500 font-mono">
                {ref?.total_refused ?? 0} recusas no total
              </span>
            </div>

            <div className="space-y-3 pt-2">
              {ref && Object.entries(ref.by_reason).length > 0 ? (
                Object.entries(ref.by_reason).map(([reason, count]) => {
                  const pct = ((count / ref.total_refused) * 100).toFixed(1);
                  let label = reason;
                  let desc = "";
                  if (reason === "below_threshold") {
                    label = "Gate 1: Corte de Cosseno (below_threshold)";
                    desc = "Similaridade abaixo do limiar (0.40). Rejeitado antes do LLM.";
                  } else if (reason === "not_answerable") {
                    label = "Gate 2: Sem Resposta no Excerto (not_answerable)";
                    desc = "O LLM indicou answerable=false com base no contexto delimitado.";
                  } else if (reason === "no_valid_citations") {
                    label = "Gate 3: Citação Rejeitada (no_valid_citations)";
                    desc = "O verificador determinístico rejeitou citações fabricadas.";
                  }

                  return (
                    <div key={reason} className="p-3 bg-zinc-800/40 border border-zinc-800 rounded-lg">
                      <div className="flex justify-between items-center text-xs mb-1">
                        <strong className="text-zinc-200">{label}</strong>
                        <span className="font-mono text-amber-400 font-bold">
                          {count} ({pct}%)
                        </span>
                      </div>
                      <p className="text-[11px] text-zinc-400">{desc}</p>
                    </div>
                  );
                })
              ) : (
                <div className="text-xs text-zinc-500 py-6 text-center">
                  Nenhuma recusa registada até ao momento.
                </div>
              )}
            </div>
          </div>
        </div>

        {/* Recent Queries Table */}
        <div className="bg-zinc-900/60 border border-zinc-800 rounded-xl overflow-hidden">
          <div className="p-4 border-b border-zinc-800 flex items-center justify-between">
            <h3 className="text-sm font-bold text-zinc-200 flex items-center gap-2">
              <Server className="w-4 h-4 text-zinc-400" />
              <span>Registo de Consultas Recentes (query_log)</span>
            </h3>
            <span className="text-xs font-mono text-zinc-500">Últimas 20 queries</span>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="bg-zinc-900/90 text-zinc-400 border-b border-zinc-800 font-mono uppercase text-[10px]">
                <tr>
                  <th className="py-2.5 px-4">Hora</th>
                  <th className="py-2.5 px-4">Pergunta</th>
                  <th className="py-2.5 px-4">Resultado</th>
                  <th className="py-2.5 px-4">Motivo / Gate</th>
                  <th className="py-2.5 px-4 text-right">Latência</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-zinc-800/60">
                {stats?.recent_queries.map((q) => {
                  const dateStr = new Date(q.created_at).toLocaleTimeString("pt-PT", {
                    hour: "2-digit",
                    minute: "2-digit",
                    second: "2-digit",
                  });

                  return (
                    <tr key={q.id} className="hover:bg-zinc-800/30 transition-colors font-sans">
                      <td className="py-3 px-4 text-zinc-500 font-mono text-[11px] whitespace-nowrap">
                        {dateStr}
                      </td>
                      <td className="py-3 px-4 text-zinc-200 max-w-md truncate">
                        {q.question}
                      </td>
                      <td className="py-3 px-4 whitespace-nowrap">
                        {q.refused ? (
                          <span className="inline-flex items-center gap-1 text-[11px] px-2 py-0.5 rounded-full bg-amber-950/60 border border-amber-800 text-amber-400 font-medium">
                            Recusada
                          </span>
                        ) : (
                          <span className="inline-flex items-center gap-1 text-[11px] px-2 py-0.5 rounded-full bg-emerald-950/60 border border-emerald-800 text-emerald-400 font-medium">
                            Respondida
                          </span>
                        )}
                      </td>
                      <td className="py-3 px-4 font-mono text-zinc-400 text-[11px] whitespace-nowrap">
                        {q.refusal_reason || "—"}
                      </td>
                      <td className="py-3 px-4 font-mono text-zinc-300 text-right whitespace-nowrap font-medium">
                        {q.latency_total_ms} ms
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      </main>
    </div>
  );
}
