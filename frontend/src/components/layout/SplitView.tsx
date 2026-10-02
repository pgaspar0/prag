"use client";

import React, { useState, useEffect, useRef } from "react";
import dynamic from "next/dynamic";
import {
  Upload,
  FileText,
  Trash2,
  AlertTriangle,
  RefreshCw,
  Layers,
  MessageSquare,
  FileSearch,
} from "lucide-react";
import {
  checkServerReady,
  deleteDocument,
  DocumentItem,
  getDocumentFileUrl,
  listDocuments,
  uploadDocument,
  BoundingBox,
  CitationVerified,
} from "@/lib/api-client";
import { ChatPanel } from "@/components/chat/ChatPanel";
import { Navbar } from "@/components/layout/Navbar";

// Load PdfViewer dynamically without SSR to prevent pdfjs canvas worker crashes
const DynamicPdfViewer = dynamic(
  () => import("@/components/pdf/PdfViewer").then((mod) => mod.PdfViewer),
  {
    ssr: false,
    loading: () => (
      <div className="flex flex-col items-center justify-center h-full bg-zinc-950 border border-zinc-800 rounded-xl text-zinc-500 gap-2">
        <div className="w-6 h-6 border-2 border-sky-500 border-t-transparent rounded-full animate-spin" />
        <span className="text-xs">A inicializar leitor de PDF...</span>
      </div>
    ),
  }
);

export function SplitView() {
  const [documents, setDocuments] = useState<DocumentItem[]>([]);
  const [selectedDocId, setSelectedDocId] = useState<string | null>(null);
  const [targetPage, setTargetPage] = useState<number>(1);
  const [highlightBBoxes, setHighlightBBoxes] = useState<BoundingBox[]>([]);
  const [mobileTab, setMobileTab] = useState<"chat" | "pdf">("chat");

  const [isServerReady, setIsServerReady] = useState<boolean>(true);
  const [isUploading, setIsUploading] = useState<boolean>(false);
  const [uploadError, setUploadError] = useState<string | null>(null);

  const fileInputRef = useRef<HTMLInputElement>(null);

  // Poll for server readiness and documents list
  const fetchDocs = async () => {
    try {
      const ready = await checkServerReady();
      setIsServerReady(ready);

      if (ready) {
        const docs = await listDocuments();
        setDocuments(docs);

        // Auto-select first ready document if none selected
        if (!selectedDocId && docs.length > 0) {
          const firstReady = docs.find((d) => d.status === "ready") || docs[0];
          setSelectedDocId(firstReady.id);
        }
      }
    } catch (err) {
      console.error("Failed fetching documents:", err);
    }
  };

  useEffect(() => {
    fetchDocs();
    const interval = setInterval(fetchDocs, 4000);
    return () => clearInterval(interval);
  }, [selectedDocId]);

  const selectedDocument = documents.find((d) => d.id === selectedDocId) || null;

  const handleSelectCitation = (citation: CitationVerified) => {
    setTargetPage(citation.page);
    setHighlightBBoxes(citation.bboxes || []);
    // On mobile, switch to pdf tab to see the citation immediately
    if (window.innerWidth < 768) {
      setMobileTab("pdf");
    }
  };

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    setIsUploading(true);
    setUploadError(null);

    try {
      const res = await uploadDocument(file);
      await fetchDocs();
      setSelectedDocId(res.document_id);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Falha ao enviar ficheiro.";
      setUploadError(msg);
    } finally {
      setIsUploading(false);
      if (fileInputRef.current) {
        fileInputRef.current.value = "";
      }
    }
  };

  const handleDelete = async (docId: string) => {
    try {
      await deleteDocument(docId);
      if (selectedDocId === docId) {
        setSelectedDocId(null);
      }
      await fetchDocs();
    } catch (err) {
      console.error("Failed deleting document:", err);
    }
  };

  return (
    <div className="flex flex-col h-screen bg-zinc-950 text-zinc-100 overflow-hidden font-sans">
      {/* Top Navbar */}
      <Navbar />

      {/* Mobile view switchers */}
      <div className="flex md:hidden bg-zinc-900 border-b border-zinc-800 p-2 justify-center shrink-0">
        <div className="flex bg-zinc-800 p-0.5 rounded-lg border border-zinc-700 w-full max-w-xs">
          <button
            onClick={() => setMobileTab("chat")}
            className={`flex-1 py-1 text-xs rounded-md font-medium text-center transition-all ${
              mobileTab === "chat"
                ? "bg-zinc-900 text-sky-400 shadow"
                : "text-zinc-400"
            }`}
          >
            Chat & Citações
          </button>
          <button
            onClick={() => setMobileTab("pdf")}
            className={`flex-1 py-1 text-xs rounded-md font-medium text-center transition-all ${
              mobileTab === "pdf"
                ? "bg-zinc-900 text-sky-400 shadow"
                : "text-zinc-400"
            }`}
          >
            Leitor de PDF
          </button>
        </div>
      </div>

      {/* Main Content: Sidebar + Split Workspace */}
      <div className="flex flex-1 overflow-hidden">
        {/* Sidebar: Documents list & Upload */}
        <aside className="w-72 border-r border-zinc-800 bg-zinc-900/40 flex flex-col shrink-0 hidden lg:flex">
          {/* Upload Button */}
          <div className="p-3 border-b border-zinc-800">
            <input
              type="file"
              ref={fileInputRef}
              onChange={handleFileUpload}
              accept=".pdf,application/pdf"
              className="hidden"
            />
            <button
              onClick={() => fileInputRef.current?.click()}
              disabled={isUploading}
              className="w-full flex items-center justify-center gap-2 py-2.5 px-4 rounded-xl bg-zinc-800 hover:bg-zinc-700 text-xs font-semibold text-zinc-100 border border-zinc-700 hover:border-zinc-600 transition-all cursor-pointer shadow-sm disabled:opacity-50"
            >
              {isUploading ? (
                <>
                  <RefreshCw className="w-4 h-4 animate-spin text-sky-400" />
                  <span>A enviar PDF...</span>
                </>
              ) : (
                <>
                  <Upload className="w-4 h-4 text-sky-400" />
                  <span>Carregar Novo PDF</span>
                </>
              )}
            </button>

            {uploadError && (
              <p className="mt-2 text-[11px] text-rose-400 leading-tight">
                {uploadError}
              </p>
            )}

            <div className="mt-2.5 p-2 rounded-lg bg-zinc-950/70 border border-zinc-800 text-[10px] text-zinc-400 leading-relaxed flex items-start gap-1.5">
              <span className="text-amber-400 font-bold shrink-0">ℹ</span>
              <span>
                Não carregues documentos confidenciais nesta demonstração pública. Os documentos carregados são eliminados automaticamente após 24 horas.
              </span>
            </div>
          </div>

          {/* Document list */}
          <div className="flex-1 overflow-y-auto p-2 space-y-1">
            <div className="px-2 py-1 text-[11px] font-semibold text-zinc-500 uppercase tracking-wider">
              Documentos Disponíveis
            </div>

            {documents.length === 0 ? (
              <div className="text-center p-6 text-zinc-500 text-xs">
                Nenhum documento carregado.
              </div>
            ) : (
              documents.map((doc) => {
                const isSelected = doc.id === selectedDocId;
                const isReady = doc.status === "ready";

                return (
                  <div
                    key={doc.id}
                    onClick={() => isReady && setSelectedDocId(doc.id)}
                    className={`group relative flex items-center justify-between p-2.5 rounded-xl border transition-all cursor-pointer ${
                      isSelected
                        ? "bg-sky-950/40 border-sky-800 text-sky-200"
                        : "bg-zinc-900/60 border-zinc-800/80 hover:bg-zinc-800/60 text-zinc-300"
                    }`}
                  >
                    <div className="flex items-center gap-2.5 min-w-0">
                      <FileText
                        className={`w-4 h-4 shrink-0 ${
                          isSelected ? "text-sky-400" : "text-zinc-500"
                        }`}
                      />
                      <div className="min-w-0">
                        <p className="text-xs font-medium truncate">
                          {doc.filename}
                        </p>
                        <div className="flex items-center gap-2 text-[10px] text-zinc-500 mt-0.5">
                          {doc.is_demo && (
                            <span className="text-amber-400 font-mono">DEMO</span>
                          )}
                          <span>
                            {doc.page_count ? `${doc.page_count} pág.` : "—"}
                          </span>
                          {!isReady && (
                            <span className="text-sky-400 animate-pulse">
                              {doc.status} ({doc.progress}p)
                            </span>
                          )}
                        </div>
                      </div>
                    </div>

                    {!doc.is_demo && (
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          handleDelete(doc.id);
                        }}
                        className="opacity-0 group-hover:opacity-100 p-1 hover:text-rose-400 transition-opacity"
                        title="Apagar documento"
                      >
                        <Trash2 className="w-3.5 h-3.5" />
                      </button>
                    )}
                  </div>
                );
              })
            )}
          </div>
        </aside>

        {/* Workspace: Split Layout */}
        <main className="flex-1 flex overflow-hidden p-3 gap-3">
          {/* Chat Column */}
          <div
            className={`flex-1 h-full flex flex-col ${
              mobileTab === "chat" ? "flex" : "hidden md:flex"
            }`}
          >
            <ChatPanel
              selectedDocument={selectedDocument}
              onSelectCitation={handleSelectCitation}
            />
          </div>

          {/* PDF Viewer Column */}
          <div
            className={`flex-1 h-full flex flex-col ${
              mobileTab === "pdf" ? "flex" : "hidden md:flex"
            }`}
          >
            {selectedDocument ? (
              <DynamicPdfViewer
                pdfUrl={getDocumentFileUrl(selectedDocument.id)}
                targetPage={targetPage}
                highlightBBoxes={highlightBBoxes}
              />
            ) : (
              <div className="flex flex-col items-center justify-center h-full bg-zinc-950 border border-zinc-800 rounded-xl text-zinc-500 p-8 text-center">
                <FileSearch className="w-10 h-10 mb-2 text-zinc-600" />
                <p className="text-sm font-semibold text-zinc-400">
                  Nenhum documento selecionado
                </p>
                <p className="text-xs text-zinc-500 mt-1 max-w-sm">
                  Escolha um documento na barra lateral ou envie um novo PDF para ver a pré-visualização com salto e destaque automático.
                </p>
              </div>
            )}
          </div>
        </main>
      </div>
    </div>
  );
}
