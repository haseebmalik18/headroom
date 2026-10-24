import { useLayoutEffect, useRef, useState } from "react";

/** Track an element's rendered size so SVG text stays at its real pixel size. */
export function useSize<T extends HTMLElement>(initial = { width: 320, height: 600 }) {
  const ref = useRef<T>(null);
  const [size, setSize] = useState(initial);
  useLayoutEffect(() => {
    if (!ref.current) return;
    const observer = new ResizeObserver(([entry]) =>
      setSize({ width: Math.round(entry.contentRect.width), height: Math.round(entry.contentRect.height) }));
    observer.observe(ref.current);
    return () => observer.disconnect();
  }, []);
  return [ref, size] as const;
}
