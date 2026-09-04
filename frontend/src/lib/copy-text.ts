function canUseAsyncClipboard(): boolean {
  return (
    typeof window !== "undefined" &&
    window.isSecureContext &&
    typeof navigator.clipboard?.writeText === "function"
  );
}

function copyTextLegacy(text: string): void {
  const textarea = document.createElement("textarea");
  textarea.value = text;
  textarea.setAttribute("readonly", "");
  textarea.setAttribute("aria-hidden", "true");
  textarea.style.cssText =
    "position:fixed;left:-9999px;top:0;opacity:0;pointer-events:none;";
  document.body.appendChild(textarea);
  try {
    textarea.select();
    textarea.setSelectionRange(0, textarea.value.length);
    if (!document.execCommand("copy")) {
      throw new Error("copy failed");
    }
  } finally {
    textarea.remove();
  }
}

/** Write text to the clipboard. Branch is chosen before any await. */
export async function copyText(text: string): Promise<void> {
  if (canUseAsyncClipboard()) {
    await navigator.clipboard.writeText(text);
    return;
  }
  copyTextLegacy(text);
}
