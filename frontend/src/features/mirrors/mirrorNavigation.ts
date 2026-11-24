import { resolveFromPath } from "@/lib/return-path";

export function mirrorDetailHref(id: string, origin: string) {
  return `/console/mirrors/${encodeURIComponent(id)}?from=${encodeURIComponent(origin)}`;
}

export function mirrorReturnHref(raw: string | null) {
  const path = resolveFromPath(raw);
  return /^\/console\/(?:catalog|mirrors)(?:[/?]|$)/.test(path) ? path : "/console/mirrors";
}

type ReturnPosition = { control: string; scroll: number[] };
const positions = new Map<string, ReturnPosition>();

function scrollParents(element: HTMLElement) {
  const parents: HTMLElement[] = [];
  for (let node = element.parentElement; node; node = node.parentElement) {
    if (/(auto|scroll)/.test(getComputedStyle(node).overflowY)) parents.push(node);
  }
  if (document.scrollingElement instanceof HTMLElement) parents.push(document.scrollingElement);
  return parents;
}

export function rememberMirrorPosition(address: string, element: HTMLElement) {
  const control = element.dataset.mirrorReturn!;
  positions.delete(address);
  positions.set(address, { control, scroll: scrollParents(element).map(node => node.scrollTop) });
  if (positions.size > 40) positions.delete(positions.keys().next().value!);
}

export function restoreMirrorPosition(address: string) {
  const saved = positions.get(address);
  if (!saved) return;
  const target = Array.from(document.querySelectorAll<HTMLElement>("[data-mirror-return]"))
    .find(node => node.dataset.mirrorReturn === saved.control);
  if (!target) return;
  for (let node = target.parentElement; node; node = node.parentElement) {
    if (node instanceof HTMLDetailsElement) node.open = true;
  }
  if (!target.getClientRects().length) return;
  target.focus({ preventScroll: true });
  scrollParents(target).forEach((node, index) => { node.scrollTop = saved.scroll[index] ?? 0; });
}
