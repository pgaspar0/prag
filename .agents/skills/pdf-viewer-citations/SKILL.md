---
name: pdf-viewer-citations
description: >-
  Use this skill to implement the Next.js frontend PDF viewer with deep-linking,
  synchronizing citation badges in the chat with automatic page jumping and text highlighting.
---

# PDF Viewer & Deep-Link Citations Skill

This skill explains how to build the responsive Split-View interface in Next.js, connecting chat citation tags to a live PDF viewer.

## Split View UX Pattern

The interface is structured in two columns:
1. **Left Panel (Chat & Q&A)**:
   - File upload dropzone.
   - Message history with Markdown streaming.
   - Interactive Citation Badges (e.g., `[Pág. 3]`).
2. **Right Panel (PDF Viewer)**:
   - PDF rendered via `pdfjs-dist` or canvas.
   - Toolbar with page indicator, zoom, and navigation buttons.
   - Synchronized state: When user clicks a citation badge on the left, the viewer triggers `goToPage(citation.page)`.

---

## 1. Citation Click Event Handling

In the Chat message component:

```tsx
interface Citation {
  page: number;
  exact_quote: string;
}

interface MessageProps {
  content: string;
  citations: Citation[];
  onSelectCitation: (citation: Citation) => void;
}

export function MessageItem({ content, citations, onSelectCitation }: MessageProps) {
  return (
    <div className="flex flex-col gap-2 p-4 rounded-lg bg-zinc-900 border border-zinc-800">
      <p className="text-zinc-200 text-sm leading-relaxed">{content}</p>
      
      {citations.length > 0 && (
        <div className="flex flex-wrap items-center gap-2 mt-2 pt-2 border-t border-zinc-800">
          <span className="text-xs text-zinc-400 font-medium">Fontes citadas:</span>
          {citations.map((c, idx) => (
            <button
              key={idx}
              onClick={() => onSelectCitation(c)}
              className="inline-flex items-center gap-1.5 px-2.5 py-1 text-xs font-semibold text-sky-400 bg-sky-950/60 border border-sky-800/80 rounded-md hover:bg-sky-900 transition-colors"
              title={`Ver excerto: "${c.exact_quote}"`}
            >
              📄 Página {c.page}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
```

---

## 2. PDF Viewer Integration (`pdfjs-dist`)

In the PDF viewer component:

```tsx
"use client";

import { useEffect, useRef, useState } from "react";
import * as pdfjsLib from "pdfjs-dist";

// Point worker to standard CDN or public assets
pdfjsLib.GlobalWorkerOptions.workerSrc = `https://unpkg.com/pdfjs-dist@${pdfjsLib.version}/build/pdf.worker.min.mjs`;

interface PdfViewerProps {
  pdfUrl: string;
  targetPage: number;
}

export function PdfViewer({ pdfUrl, targetPage }: PdfViewerProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [pdfDoc, setPdfDoc] = useState<pdfjsLib.PDFDocumentProxy | null>(null);
  const [currentPage, setCurrentPage] = useState<number>(1);
  const [totalPages, setTotalPages] = useState<number>(0);

  // Load document
  useEffect(() => {
    const loadingTask = pdfjsLib.getDocument(pdfUrl);
    loadingTask.promise.then((doc) => {
      setPdfDoc(doc);
      setTotalPages(doc.numPages);
    });
  }, [pdfUrl]);

  // Jump to page when citation clicked
  useEffect(() => {
    if (targetPage && targetPage <= totalPages) {
      setCurrentPage(targetPage);
    }
  }, [targetPage, totalPages]);

  // Render current page
  useEffect(() => {
    if (!pdfDoc || !canvasRef.current) return;

    pdfDoc.getPage(currentPage).then((page) => {
      const viewport = page.getViewport({ scale: 1.5 });
      const canvas = canvasRef.current!;
      const context = canvas.getContext("2d")!;
      canvas.height = viewport.height;
      canvas.width = viewport.width;

      const renderContext = {
        canvasContext: context,
        viewport: viewport,
      };
      page.render(renderContext);
    });
  }, [pdfDoc, currentPage]);

  return (
    <div className="flex flex-col h-full bg-zinc-950 border border-zinc-800 rounded-xl overflow-hidden">
      <div className="flex items-center justify-between px-4 py-2 bg-zinc-900 border-b border-zinc-800">
        <span className="text-xs text-zinc-400">
          Página {currentPage} de {totalPages}
        </span>
        <div className="flex gap-2">
          <button 
            disabled={currentPage <= 1} 
            onClick={() => setCurrentPage((p) => Math.max(1, p - 1))}
            className="px-2 py-1 text-xs bg-zinc-800 rounded disabled:opacity-50 text-white"
          >
            Anterior
          </button>
          <button 
            disabled={currentPage >= totalPages} 
            onClick={() => setCurrentPage((p) => Math.min(totalPages, p + 1))}
            className="px-2 py-1 text-xs bg-zinc-800 rounded disabled:opacity-50 text-white"
          >
            Seguinte
          </button>
        </div>
      </div>
      <div className="flex-1 overflow-auto p-4 flex justify-center items-start">
        <canvas ref={canvasRef} className="shadow-2xl rounded" />
      </div>
    </div>
  );
}
```
