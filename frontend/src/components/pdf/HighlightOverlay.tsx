"use client";

import React from "react";
import { BoundingBox } from "@/lib/api-client";

interface HighlightOverlayProps {
  bboxes: BoundingBox[];
  currentPage: number;
  scale: number;
}

export function HighlightOverlay({
  bboxes,
  currentPage,
  scale,
}: HighlightOverlayProps) {
  // Filter bounding boxes for the currently viewed page
  const pageBBoxes = bboxes.filter((b) => b.page === currentPage);

  if (pageBBoxes.length === 0) {
    return null;
  }

  return (
    <div className="absolute inset-0 pointer-events-none z-10">
      {pageBBoxes.map((b, idx) => {
        const left = b.x0 * scale;
        const top = b.y0 * scale;
        const width = Math.max(4, (b.x1 - b.x0) * scale);
        const height = Math.max(10, (b.y1 - b.y0) * scale);

        return (
          <div
            key={idx}
            className="absolute bg-amber-400/35 border border-amber-500/80 rounded-sm shadow-sm transition-all duration-300 animate-pulse"
            style={{
              left: `${left}px`,
              top: `${top}px`,
              width: `${width}px`,
              height: `${height}px`,
            }}
          />
        );
      })}
    </div>
  );
}
