/**
 * Catch-all for /console/* paths with no dedicated page.tsx.
 * PageCanAccess in console/layout.tsx fail-closes unregistered paths.
 */
export default function ConsoleCatchAllPage() {
  return null;
}
