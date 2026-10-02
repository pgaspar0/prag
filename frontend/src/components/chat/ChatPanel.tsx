"use client";

import React, { useState, useRef, useEffect } from "react";
import { Send, Sparkles, AlertCircle } from "lucide-react";
import { askQuestion, CitationVerified, DocumentItem } from "@/lib/api-client";
import { ChatMessage, MessageItem } from "./MessageItem";

interface ChatPanelProps {
  selectedDocument: DocumentItem | null;
  onSelectCitation: (citation: CitationVerified) => void;
}

export function ChatPanel({
  selectedDocument,
  onSelectCitation,
}: ChatPanelProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const messagesEndRef = useRef<HTMLDivElement>(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages, loading]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim() || loading || !selectedDocument) return;

    const userText = input.trim();
    setInput("");
    setError(null);

    const userMsg: ChatMessage = {
      id: crypto.randomUUID(),
      sender: "user",
      text: userText,
      timestamp: new Date(),
    };

    setMessages((prev) => [...prev, userMsg]);
    setLoading(true);

    try {
      const res = await askQuestion([selectedDocument.id], userText);

      const assistantMsg: ChatMessage = {
        id: crypto.randomUUID(),
        sender: "assistant",
        text: res.answer,
        refused: res.refused,
        refusalReason: res.refusal_reason,
        citations: res.citations,
        latencyMs: res.latency_ms,
        timestamp: new Date(),
      };

      setMessages((prev) => [...prev, assistantMsg]);

      // If response has verified citations, highlight the first one automatically
      if (res.citations && res.citations.length > 0) {
        onSelectCitation(res.citations[0]);
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Falha ao obter resposta.";
      setError(msg);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex flex-col h-full bg-zinc-950 border border-zinc-800 rounded-xl overflow-hidden shadow-xl">
      {/* Header */}
      <div className="px-4 py-3 bg-zinc-900/90 border-b border-zinc-800 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <div className="p-1.5 rounded-lg bg-sky-500/10 text-sky-400">
            <Sparkles className="w-4 h-4" />
          </div>
          <div>
            <h3 className="text-sm font-semibold text-zinc-100">
              Perguntas e Citações
            </h3>
            <p className="text-[11px] text-zinc-400 truncate max-w-[260px]">
              {selectedDocument
                ? selectedDocument.filename
                : "Selecione um documento para perguntar"}
            </p>
          </div>
        </div>
      </div>

      {/* Messages Scroll Area */}
      <div className="flex-1 overflow-y-auto p-4 space-y-2">
        {messages.length === 0 && (
          <div className="flex flex-col items-center justify-center h-full text-center p-6 text-zinc-500">
            <Sparkles className="w-8 h-8 mb-2 text-zinc-600" />
            <p className="text-sm font-medium text-zinc-400">
              Faça perguntas sobre o documento selecionado
            </p>
            <p className="text-xs mt-1 text-zinc-500 max-w-xs">
              As respostas incluem citações com a página exata e o destaque do texto original. Perguntas sem resposta são recusadas sem alucinar.
            </p>
          </div>
        )}

        {messages.map((m) => (
          <MessageItem
            key={m.id}
            message={m}
            onSelectCitation={onSelectCitation}
          />
        ))}

        {loading && (
          <div className="flex items-center gap-2 text-xs text-zinc-400 p-3 bg-zinc-900/60 rounded-xl border border-zinc-800/80 w-fit animate-pulse">
            <div className="w-4 h-4 border-2 border-sky-400 border-t-transparent rounded-full animate-spin" />
            <span>A analisar excertos e validar citações...</span>
          </div>
        )}

        {error && (
          <div className="flex items-center gap-2 text-xs text-rose-400 p-3 bg-rose-950/20 border border-rose-900/50 rounded-xl">
            <AlertCircle className="w-4 h-4 shrink-0" />
            <span>{error}</span>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* Input Box */}
      <form
        onSubmit={handleSubmit}
        className="p-3 bg-zinc-900/80 border-t border-zinc-800 flex items-center gap-2"
      >
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder={
            selectedDocument?.status === "ready"
              ? "Ex: Qual é o prazo de pagamento ou multa aplicável?"
              : "Aguarde o processamento do documento..."
          }
          disabled={!selectedDocument || selectedDocument.status !== "ready" || loading}
          className="flex-1 px-3.5 py-2 text-sm bg-zinc-950 border border-zinc-800 rounded-lg text-zinc-200 placeholder-zinc-500 focus:outline-none focus:border-sky-500 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
        />
        <button
          type="submit"
          disabled={!input.trim() || loading || !selectedDocument || selectedDocument.status !== "ready"}
          aria-label="Enviar pergunta"
          className="p-2.5 rounded-lg bg-sky-600 text-white hover:bg-sky-500 disabled:opacity-40 disabled:cursor-not-allowed transition-all cursor-pointer shadow-md"
        >
          <Send className="w-4 h-4" />
        </button>
      </form>
    </div>
  );
}
