export type CatalogStatusTone = {
  labelKey: string;
  color: "green" | "gray";
};

export function catalogPresence(isPresent: boolean): CatalogStatusTone {
  return {
    labelKey: isPresent
      ? "catalog.fields.presentValue"
      : "catalog.fields.absentValue",
    color: isPresent ? "green" : "gray",
  };
}

export function catalogSemanticsReady(ready: boolean): CatalogStatusTone {
  return {
    labelKey: ready ? "catalog.semantics.ready" : "catalog.semantics.notReady",
    color: ready ? "green" : "gray",
  };
}
