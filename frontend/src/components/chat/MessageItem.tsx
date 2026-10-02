"use client";

import React from "react";
import { CitationVerified, LatencyBreakdown } from "@/lib/api-client";
import { FileText, ShieldAlert, CheckCircle2, Clock } from "lucide-react";

export interface ChatMessage {
  id: string;
  sender: "user" | "assistant";
  text: string;
  refused?: boolean;
  refusalReason?: string | null;
  citations?: CitationVerified[];
  latencyMs?: LatencyBreakdown;
  timestamp: Date;
}

interface MessageItemProps {
  message: ChatMessage;
  onSelectCitation?: (citation: CitationVerified) => void;
}

export function MessageItem({ message, onSelectCitation }: MessageItemProps) {
  const isUser = message.sender === "user";

  if (isUser) {
    return (
      <div className="flex justify-end mb-4">
        <div className="max-w-[85%] bg-sky-600 text-white px-4 py-2.5 rounded-2xl rounded-tr-sm text-sm shadow-md">
          <p className="leading-relaxed whitespace-pre-wrap">{message.text}</p>
        </div>
      </div>
    );
  }

  // Assistant response
  const isRefusal = message.refused;

  return (
    <div className="flex flex-col mb-4 max-w-[95%]">
      <div
        className={`p-4 rounded-2xl rounded-tl-sm border text-sm leading-relaxed shadow-sm transition-all ${
          isRefusal
            ? "bg-amber-950/20 border-amber-800/40 text-amber-200"
            : "bg-zinc-900 border-zinc-800 text-zinc-200"
        }`}
      >
        {/* Header indicator */}
        <div className="flex items-center justify-between mb-2">
          <span className="text-[11px] font-semibold tracking-wider uppercase flex items-center gap-1.5">
            {isRefusal ? (
              <>
                <ShieldAlert className="w-3.5 h-3.5 text-amber-400" />
                <span className="text-amber-400">Recusa Verificada</span>
                {message.refusalReason && (
                  <span className="text-[10px] px-1.5 py-0.5 rounded bg-amber-950/60 border border-amber-800/60 text-amber-300 font-mono">
                    {message.refusalReason}
                  </span>
                )}
              </>
            ) : (
              <>
                <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />
                <span className="text-emerald-400">Resposta com Citação Fiel</span>
              </>
            )}
          </span>

          {message.latencyMs && (
            <span className="text-[11px] text-zinc-500 font-mono flex items-center gap-1">
              <Clock className="w-3 h-3" />
              {message.latencyMs.total}ms
            </span>
          )}
        </div>

        {/* Content text */}
        <p className="whitespace-pre-wrap">{message.text}</p>

        {/* Citations Badges */}
        {message.citations && message.citations.length > 0 && (
          <div className="mt-3 pt-3 border-t border-zinc-800 flex flex-col gap-1.5">
            <span className="text-[11px] text-zinc-400 font-medium">
              Passagens citadas no documento:
            </span>
            <div className="flex flex-wrap gap-2">
              {message.citations.map((c, idx) => (
                <button
                  key={idx}
                  onClick={() => onSelectCitation && onSelectCitation(c)}
                  className="inline-flex items-center gap-1.5 px-2.5 py-1 text-xs font-medium text-sky-300 bg-sky-950/70 border border-sky-800/80 rounded-md hover:bg-sky-900/90 hover:border-sky-600 transition-all cursor-pointer group text-left"
                  title={`Clique para ir à página ${c.page} e ver o excerto citado`}
                >
                  <FileText className="w-3.5 h-3.5 text-sky-400 group-hover:scale-110 transition-transform" />
                  <span>Página {c.page}</span>
                </button>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
