"use client";

import { VisuallyHidden } from "@mantine/core";
import { useEffect, useRef, useState } from "react";

/** Returns the latest status label after the first one, for a polite live region. */
export function useLiveAnnouncement(text: string): string {
  const [announced, setAnnounced] = useState("");
  const seen = useRef<string | null>(null);

  useEffect(() => {
    if (!text) return;
    if (seen.current === null) {
      seen.current = text;
      return;
    }
    if (seen.current !== text) {
      seen.current = text;
      setAnnounced(text);
    }
  }, [text]);

  return announced;
}

export function LiveStatusAnnouncer({ text }: { text: string }) {
  const announced = useLiveAnnouncement(text);
  return (
    <VisuallyHidden>
      <div role="status" aria-live="polite">
        {announced}
      </div>
    </VisuallyHidden>
  );
}
