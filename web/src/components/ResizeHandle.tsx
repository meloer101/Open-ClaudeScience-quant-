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
      className="relative z-10 w-1 shrink-0 -mx-1 cursor-col-resize bg-transparent hover:bg-warm-300 active:bg-warm-400 transition-colors"
    />
  );
}
