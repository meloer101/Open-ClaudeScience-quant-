import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import * as pdfjsLib from "pdfjs-dist";
import workerUrl from "pdfjs-dist/build/pdf.worker.min.mjs?url";
import "pdfjs-dist/web/pdf_viewer.css";
import { askPaper, getPaper, paperPdfUrl, reproducePaper } from "../api/client";
import type { AskPaperResponse } from "../types";

pdfjsLib.GlobalWorkerOptions.workerSrc = workerUrl;

const SCALE = 1.35;

interface Selection {
  text: string;
  page: number;
  rect: { top: number; left: number };
}

interface LiteratureViewerProps {
  paperId: string;
  onOpenRun: (runId: string) => void;
}

export function LiteratureViewer({ paperId, onOpenRun }: LiteratureViewerProps) {
  const { data: paper } = useQuery({ queryKey: ["paper", paperId], queryFn: () => getPaper(paperId) });
  const scrollRef = useRef<HTMLDivElement>(null);
  const [selection, setSelection] = useState<Selection | null>(null);
  const [panel, setPanel] = useState<null | { selection: string; page: number; mode: "ask" | "reproduce" }>(null);

  usePdfRender(paperId, scrollRef);

  // Turn a text selection inside the PDF into an anchored popover. The page
  // number comes from the data-page attribute on the enclosing page wrapper.
  const handleMouseUp = () => {
    const sel = window.getSelection();
    const text = sel?.toString().trim() ?? "";
    if (!text || !scrollRef.current || !sel || sel.rangeCount === 0) {
      setSelection(null);
      return;
    }
    const range = sel.getRangeAt(0);
    let node: Node | null = range.commonAncestorContainer;
    let pageEl: HTMLElement | null = null;
    while (node) {
      if (node instanceof HTMLElement && node.dataset.page) {
        pageEl = node;
        break;
      }
      node = node.parentNode;
    }
    if (!pageEl) {
      setSelection(null);
      return;
    }
    const rect = range.getBoundingClientRect();
    const containerRect = scrollRef.current.getBoundingClientRect();
    setSelection({
      text,
      page: Number(pageEl.dataset.page),
      rect: {
        top: rect.top - containerRect.top + scrollRef.current.scrollTop + rect.height + 6,
        left: rect.left - containerRect.left,
      },
    });
  };

  return (
    <div className="flex-1 flex min-w-0 min-h-0">
      <div className="flex-1 flex flex-col min-w-0 min-h-0">
        <div className="px-4 py-2 border-b border-warm-100 bg-white">
          <div className="text-sm font-medium text-warm-900 truncate">{paper?.title ?? "Loading paper…"}</div>
          <div className="text-xs text-warm-400 truncate">
            {paper?.authors?.join(", ") || "—"} · {paper?.n_pages ?? "?"} pages
            {paper?.arxiv_id ? ` · arXiv:${paper.arxiv_id}` : ""}
          </div>
        </div>
        <div ref={scrollRef} onMouseUp={handleMouseUp} className="relative flex-1 overflow-auto bg-warm-50 p-4">
          <div id={`pdf-pages-${paperId}`} className="flex flex-col items-center gap-4" />
          {selection && (
            <div
              className="absolute z-20 flex gap-1 bg-warm-900 rounded-lg shadow-lg p-1"
              style={{ top: selection.rect.top, left: selection.rect.left }}
            >
              <button
                className="text-xs text-white px-2 py-1 rounded hover:bg-warm-700"
                onMouseDown={(e) => {
                  e.preventDefault();
                  setPanel({ selection: selection.text, page: selection.page, mode: "ask" });
                  setSelection(null);
                }}
              >
                就此提问
              </button>
              <button
                className="text-xs text-white px-2 py-1 rounded hover:bg-warm-700"
                onMouseDown={(e) => {
                  e.preventDefault();
                  setPanel({ selection: selection.text, page: selection.page, mode: "reproduce" });
                  setSelection(null);
                }}
              >
                提炼成因子并复现
              </button>
            </div>
          )}
        </div>
      </div>
      {panel && (
        <SelectionPanel
          paperId={paperId}
          selection={panel.selection}
          page={panel.page}
          mode={panel.mode}
          onClose={() => setPanel(null)}
          onOpenRun={onOpenRun}
        />
      )}
    </div>
  );
}

function SelectionPanel({
  paperId,
  selection,
  page,
  mode,
  onClose,
  onOpenRun,
}: {
  paperId: string;
  selection: string;
  page: number;
  mode: "ask" | "reproduce";
  onClose: () => void;
  onOpenRun: (runId: string) => void;
}) {
  const [question, setQuestion] = useState("这段讲的是什么？如何把它实现成一个可回测的因子？");
  const [answer, setAnswer] = useState<AskPaperResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const ask = async () => {
    setBusy(true);
    setError(null);
    try {
      setAnswer(await askPaper(paperId, { selection, question, page }));
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  };

  const reproduce = async () => {
    setBusy(true);
    setError(null);
    try {
      const { run_id } = await reproducePaper(paperId, { selection, page });
      onOpenRun(run_id);
      onClose();
    } catch (e) {
      setError(String(e));
      setBusy(false);
    }
  };

  return (
    <div className="w-96 shrink-0 border-l border-warm-100 bg-white flex flex-col min-h-0">
      <div className="px-3 py-2 border-b border-warm-100 flex items-center justify-between">
        <span className="text-sm font-medium text-warm-800">{mode === "ask" ? "就选中内容提问" : "提炼成因子并复现"}</span>
        <button onClick={onClose} className="text-warm-400 hover:text-warm-700 text-sm">✕</button>
      </div>
      <div className="p-3 overflow-y-auto flex-1 space-y-3">
        <div>
          <div className="text-xs text-warm-400 mb-1">选中内容 · 第 {page} 页</div>
          <blockquote className="text-xs text-warm-700 border-l-2 border-accent-200 pl-2 whitespace-pre-wrap max-h-32 overflow-y-auto">
            {selection}
          </blockquote>
        </div>

        {mode === "ask" ? (
          <>
            <textarea
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              rows={3}
              className="w-full text-sm border border-warm-150 rounded-md px-2 py-1.5"
            />
            <button
              onClick={() => void ask()}
              disabled={busy || !question.trim()}
              className="w-full text-sm px-2 py-1.5 rounded-md bg-warm-900 text-white disabled:bg-warm-150 disabled:text-warm-500"
            >
              {busy ? "思考中…" : "提问"}
            </button>
            {answer && (
              <div className="text-sm text-warm-800 whitespace-pre-wrap border border-warm-100 rounded-md p-2 bg-warm-25">
                {answer.answer}
              </div>
            )}
          </>
        ) : (
          <>
            <div className="text-xs text-warm-500">
              将基于选中段落提炼因子定义，生成 <code>compute()</code>，走审查台后回测，并生成"论文 vs 复现"对比表。
            </div>
            <button
              onClick={() => void reproduce()}
              disabled={busy}
              className="w-full text-sm px-2 py-1.5 rounded-md bg-accent-600 text-white disabled:bg-warm-150 disabled:text-warm-500"
            >
              {busy ? "启动中…" : "开始复现"}
            </button>
          </>
        )}
        {error && <div className="text-xs text-danger-600 whitespace-pre-wrap">{error}</div>}
      </div>
    </div>
  );
}

// Renders every page of the PDF (canvas + selectable pdfjs text layer) into the
// #pdf-pages-<id> container. Kept as a hook so the component body stays about
// selection/UX, not pdfjs plumbing.
function usePdfRender(paperId: string, scrollRef: React.RefObject<HTMLDivElement | null>) {
  const url = useMemo(() => paperPdfUrl(paperId), [paperId]);
  useEffect(() => {
    let cancelled = false;
    const container = scrollRef.current?.querySelector(`#pdf-pages-${paperId}`) as HTMLElement | null;
    if (!container) return;
    container.innerHTML = "";

    (async () => {
      const pdf = await pdfjsLib.getDocument(url).promise;
      for (let pageNumber = 1; pageNumber <= pdf.numPages; pageNumber++) {
        if (cancelled) return;
        const page = await pdf.getPage(pageNumber);
        const viewport = page.getViewport({ scale: SCALE });

        const wrapper = document.createElement("div");
        wrapper.dataset.page = String(pageNumber);
        wrapper.className = "relative bg-white shadow-sm";
        wrapper.style.width = `${viewport.width}px`;
        wrapper.style.height = `${viewport.height}px`;
        // pdfjs v4 text layer sizes/positions its spans off this CSS variable.
        wrapper.style.setProperty("--scale-factor", String(SCALE));

        const canvas = document.createElement("canvas");
        canvas.width = viewport.width;
        canvas.height = viewport.height;
        wrapper.appendChild(canvas);

        const textLayerDiv = document.createElement("div");
        textLayerDiv.className = "textLayer";
        textLayerDiv.style.width = `${viewport.width}px`;
        textLayerDiv.style.height = `${viewport.height}px`;
        wrapper.appendChild(textLayerDiv);
        container.appendChild(wrapper);

        const ctx = canvas.getContext("2d");
        if (ctx) await page.render({ canvasContext: ctx, viewport }).promise;

        const textContent = await page.getTextContent();
        const textLayer = new pdfjsLib.TextLayer({ textContentSource: textContent, container: textLayerDiv, viewport });
        await textLayer.render();
      }
    })().catch((e) => {
      if (!cancelled) console.error("pdf render failed", e);
    });

    return () => {
      cancelled = true;
    };
  }, [paperId, url, scrollRef]);
}
