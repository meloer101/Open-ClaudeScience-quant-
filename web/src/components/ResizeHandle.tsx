import { useCallback, useRef } from "react";

interface ResizeHandleProps {
  /** Called with the incremental horizontal delta (px) as the mouse moves. */
  onResize: (deltaX: number) => void;
}

export function ResizeHandle({ onResize }: ResizeHandleProps) {
  const draggingRef = useRef(false);

  const handleMouseDown = useCallback(
    (event: React.MouseEvent) => {
      event.preventDefault();
      draggingRef.current = true;
      let lastX = event.clientX;

      const handleMouseMove = (moveEvent: MouseEvent) => {
        if (!draggingRef.current) return;
        const delta = moveEvent.clientX - lastX;
        lastX = moveEvent.clientX;
        onResize(delta);
      };
      const handleMouseUp = () => {
        draggingRef.current = false;
        window.removeEventListener("mousemove", handleMouseMove);
        window.removeEventListener("mouseup", handleMouseUp);
        document.body.style.cursor = "";
        document.body.style.userSelect = "";
      };

      document.body.style.cursor = "col-resize";
      document.body.style.userSelect = "none";
      window.addEventListener("mousemove", handleMouseMove);
      window.addEventListener("mouseup", handleMouseUp);
    },
    [onResize],
  );

  return (
    <div
      onMouseDown={handleMouseDown}
      role="separator"
      aria-orientation="vertical"
      className="w-2.5 shrink-0 cursor-col-resize group flex justify-center"
    >
      <div className="w-px h-full bg-warm-150 group-hover:bg-warm-400 group-active:bg-warm-500 transition-colors" />
    </div>
  );
}
