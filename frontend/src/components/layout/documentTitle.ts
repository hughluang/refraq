let brandName = "";
let pageTitle: string | null = null;

function apply() {
  if (!pageTitle) {
    document.title = brandName;
    return;
  }
  document.title = brandName ? `${pageTitle} · ${brandName}` : pageTitle;
}

export function setBrandDocumentTitle(next: string) {
  brandName = next;
  apply();
}

export function setPageDocumentTitle(next: string | null) {
  pageTitle = next;
  apply();
}
