"use client";

import React, { useEffect, useRef, useState } from "react";
import * as pdfjsLib from "pdfjs-dist";
import { ChevronLeft, ChevronRight, ZoomIn, ZoomOut, RotateCcw } from "lucide-react";
import { BoundingBox } from "@/lib/api-client";
import { HighlightOverlay } from "./HighlightOverlay";

// Configure local worker from public directory
if (typeof window !== "undefined" && !pdfjsLib.GlobalWorkerOptions.workerSrc) {
  pdfjsLib.GlobalWorkerOptions.workerSrc = "/pdf.worker.min.mjs";
}

interface PdfViewerProps {
  pdfUrl: string;
  targetPage?: number;
  highlightBBoxes?: BoundingBox[];
}

export function PdfViewer({
  pdfUrl,
  targetPage,
  highlightBBoxes = [],
}: PdfViewerProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  const [pdfDoc, setPdfDoc] = useState<pdfjsLib.PDFDocumentProxy | null>(null);
  const [currentPage, setCurrentPage] = useState<number>(1);
  const [totalPages, setTotalPages] = useState<number>(0);
  const [scale, setScale] = useState<number>(1.3);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  // Load document
  useEffect(() => {
    if (!pdfUrl) return;

    let isCancelled = false;
    setLoading(true);
    setError(null);

    const loadingTask = pdfjsLib.getDocument({
      url: pdfUrl,
      withCredentials: true,
    });

    loadingTask.promise
      .then((doc) => {
        if (isCancelled) {
          doc.destroy();
          return;
        }
        setPdfDoc(doc);
        setTotalPages(doc.numPages);
        setCurrentPage(targetPage || 1);
        setLoading(false);
      })
      .catch((err) => {
        if (
          isCancelled ||
          err?.name === "RenderingCancelledException" ||
          err?.message?.includes("Worker was destroyed")
        ) {
          return;
        }
        console.error("Failed to load PDF:", err);
        setError("Não foi possível carregar o documento PDF.");
        setLoading(false);
      });

    return () => {
      isCancelled = true;
      try {
        loadingTask.destroy();
      } catch {
        // ignore cancellation
      }
    };
  }, [pdfUrl]);

  // Jump to target page when citation is clicked
  useEffect(() => {
    if (targetPage && targetPage >= 1 && targetPage <= totalPages) {
      setCurrentPage(targetPage);
    }
  }, [targetPage, totalPages]);

  // Render current page onto canvas
  useEffect(() => {
    if (!pdfDoc || !canvasRef.current) return;

    let isCancelled = false;
    let renderTask: pdfjsLib.RenderTask | null = null;

    pdfDoc
      .getPage(currentPage)
      .then((page) => {
        if (isCancelled) return;
        const viewport = page.getViewport({ scale });
        const canvas = canvasRef.current;
        if (!canvas) return;

        const context = canvas.getContext("2d");
        if (!context) return;

        canvas.height = viewport.height;
        canvas.width = viewport.width;

        const renderContext = {
          canvasContext: context,
          viewport: viewport,
        };

        renderTask = page.render(renderContext);
        renderTask.promise.catch((err) => {
          if (
            isCancelled ||
            err?.name === "RenderingCancelledException" ||
            err?.message?.includes("Worker was destroyed")
          ) {
            return;
          }
          console.error("Render error:", err);
        });
      })
      .catch((err) => {
        if (
          isCancelled ||
          err?.name === "RenderingCancelledException" ||
          err?.message?.includes("Worker was destroyed")
        ) {
          return;
        }
        console.error("GetPage error:", err);
      });

    return () => {
      isCancelled = true;
      if (renderTask) {
        renderTask.cancel();
      }
    };
  }, [pdfDoc, currentPage, scale]);

  return (
    <div className="flex flex-col h-full bg-zinc-950 border border-zinc-800 rounded-xl overflow-hidden shadow-xl">
      {/* Viewer Toolbar */}
      <div className="flex items-center justify-between px-4 py-2.5 bg-zinc-900/90 border-b border-zinc-800 text-zinc-300">
        <div className="flex items-center gap-2">
          <button
            onClick={() => setCurrentPage((p) => Math.max(1, p - 1))}
            disabled={currentPage <= 1 || loading}
            aria-label="Página anterior"
            className="p-1.5 rounded hover:bg-zinc-800 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
          >
            <ChevronLeft className="w-4 h-4" />
          </button>
          <span className="text-xs font-mono text-zinc-400">
            Pág. <span className="text-zinc-100 font-semibold">{currentPage}</span> / {totalPages || 1}
          </span>
          <button
            onClick={() => setCurrentPage((p) => Math.min(totalPages, p + 1))}
            disabled={currentPage >= totalPages || loading}
            aria-label="Página seguinte"
            className="p-1.5 rounded hover:bg-zinc-800 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
          >
            <ChevronRight className="w-4 h-4" />
          </button>
        </div>

        <div className="flex items-center gap-1.5">
          <button
            onClick={() => setScale((s) => Math.max(0.8, s - 0.15))}
            aria-label="Diminuir zoom"
            className="p-1.5 rounded hover:bg-zinc-800 transition-colors"
            title="Diminuir zoom"
          >
            <ZoomOut className="w-4 h-4" />
          </button>
          <span className="text-xs font-mono text-zinc-400 w-12 text-center">
            {Math.round(scale * 100)}%
          </span>
          <button
            onClick={() => setScale((s) => Math.min(2.5, s + 0.15))}
            aria-label="Aumentar zoom"
            className="p-1.5 rounded hover:bg-zinc-800 transition-colors"
            title="Aumentar zoom"
          >
            <ZoomIn className="w-4 h-4" />
          </button>
          <button
            onClick={() => setScale(1.3)}
            aria-label="Redefinir zoom"
            className="p-1.5 rounded hover:bg-zinc-800 transition-colors"
            title="Redefinir zoom"
          >
            <RotateCcw className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>

      {/* Viewer Content Area */}
      <div
        ref={containerRef}
        className="flex-1 overflow-auto p-4 flex justify-center items-start bg-zinc-950/80"
      >
        {loading && (
          <div className="flex flex-col items-center justify-center h-64 text-zinc-400 gap-2">
            <div className="w-6 h-6 border-2 border-sky-500 border-t-transparent rounded-full animate-spin" />
            <p className="text-xs">A carregar documento PDF...</p>
          </div>
        )}

        {error && (
          <div className="flex flex-col items-center justify-center h-64 text-rose-400 text-xs text-center p-4">
            <p className="font-semibold">{error}</p>
          </div>
        )}

        {!loading && !error && (
          <div className="relative shadow-2xl rounded-md overflow-hidden bg-white">
            <canvas ref={canvasRef} className="block" />
            <HighlightOverlay
              bboxes={highlightBBoxes}
              currentPage={currentPage}
              scale={scale}
            />
          </div>
        )}
      </div>
    </div>
  );
}
