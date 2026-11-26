"use client";

import { useCan, useNotification, useTranslate } from "@refinedev/core";
import { useEffect, useMemo, useRef, useState } from "react";

import { runObjectSample } from "@/features/sources/api/sample";
import {
  isAccessEvaluationPending,
  ModuleAction,
  ModuleId,
} from "@/features/console/module-identity";
import { isSampleEligible } from "@/features/sources/catalog-detail/catalogObjectKind";
import {
  buildSampleRequest,
  defaultSampleOrderColumn,
  isSampleStale,
  isUnstableOrder,
  sampleFilterSnapshot,
  type SampleAppliedParams,
  type SampleFilter,
  type SampleFilterDraft,
} from "@/features/sources/catalog-detail/sampleFilters";
import type { CatalogObject, SampleResult } from "@/features/sources/types";
import { ApiError } from "@/lib/api";
import { problemMessage } from "@/lib/problem";

function createEmptyFilter(id: string): SampleFilterDraft {
  return {
    id,
    column: null,
    op: "eq",
    value: "",
  };
}

export const DEFAULT_SAMPLE_LIMIT = 50;

export function useCatalogSample(object: CatalogObject) {
  const t = useTranslate();
  const { open } = useNotification();
  const { data: canSampleData, isLoading: canSampleQueryLoading } = useCan({
    resource: ModuleId.catalog,
    action: ModuleAction.sample,
  });
  const canSamplePending = isAccessEvaluationPending(
    canSampleQueryLoading,
    canSampleData,
  );
  const canSample = !canSamplePending && Boolean(canSampleData?.can);

  const nextFilterId = useRef(1);
  const [limit, setLimit] = useState(DEFAULT_SAMPLE_LIMIT);
  const [offset, setOffset] = useState(0);
  const [filters, setFilters] = useState<SampleFilterDraft[]>(() => [
    createEmptyFilter("0"),
  ]);
  const [selectedColumns, setSelectedColumns] = useState<string[]>([]);
  const [includeSql, setIncludeSql] = useState(false);
  const [orderColumn, setOrderColumn] = useState<string | null>(() =>
    defaultSampleOrderColumn(object),
  );
  const [orderDirection, setOrderDirection] = useState<"asc" | "desc">("asc");
  const [result, setResult] = useState<SampleResult | null>(null);
  const [applied, setApplied] = useState<SampleAppliedParams | null>(null);
  const [forbidden, setForbidden] = useState(false);
  const [running, setRunning] = useState(false);

  useEffect(() => {
    nextFilterId.current = 1;
    setLimit(DEFAULT_SAMPLE_LIMIT);
    setOffset(0);
    setFilters([createEmptyFilter("0")]);
    setSelectedColumns([]);
    setIncludeSql(false);
    setOrderColumn(defaultSampleOrderColumn(object));
    setOrderDirection("asc");
    setResult(null);
    setApplied(null);
    setForbidden(false);
  }, [object.id]);

  const filter = filters[0] ?? createEmptyFilter("0");

  const setFilter = (
    updater: SampleFilter | ((prev: SampleFilter) => SampleFilter),
  ) => {
    setFilters((prev) => {
      const current = prev[0] ?? createEmptyFilter("0");
      const next = typeof updater === "function" ? updater(current) : updater;
      const updated: SampleFilterDraft = { ...next, id: current.id };
      return prev.length <= 1 ? [updated] : [updated, ...prev.slice(1)];
    });
  };

  const addFilter = () => {
    const id = String(nextFilterId.current++);
    setFilters((prev) => [...prev, createEmptyFilter(id)]);
  };

  const removeFilter = (id: string) => {
    setFilters((prev) => {
      if (prev.length <= 1) {
        return [createEmptyFilter(prev[0]?.id ?? "0")];
      }
      return prev.filter((item) => item.id !== id);
    });
    setOffset(0);
  };

  const updateFilter = (id: string, patch: Partial<SampleFilter>) => {
    setFilters((prev) =>
      prev.map((item) => (item.id === id ? { ...item, ...patch } : item)),
    );
    setOffset(0);
  };

  const clearFilters = () => {
    setFilters([createEmptyFilter("0")]);
    setOffset(0);
  };

  const toggleSort = (column: string) => {
    if (orderColumn !== column) {
      setOrderColumn(column);
      setOrderDirection("asc");
    } else if (orderDirection === "asc") {
      setOrderDirection("desc");
    } else {
      setOrderColumn(null);
      setOrderDirection("asc");
    }
    setOffset(0);
  };

  const filterKey = useMemo(() => sampleFilterSnapshot(filters), [filters]);
  const columnsKey = useMemo(
    () => JSON.stringify(selectedColumns),
    [selectedColumns],
  );
  const currentParams: SampleAppliedParams = {
    limit,
    offset,
    filterKey,
    orderColumn,
    orderDirection,
    columnsKey,
    includeSql,
  };
  const stale = Boolean(result) && isSampleStale(applied, currentParams);
  const unstableOrder = isUnstableOrder(offset, orderColumn);

  const run = async (nextOffset: number = offset) => {
    if (!isSampleEligible(object.object_type)) {
      return;
    }
    setRunning(true);
    try {
      const body = buildSampleRequest(
        filters,
        orderColumn,
        orderDirection,
        nextOffset,
        limit,
        result?.declarations ?? [],
        {
          columns: selectedColumns,
          includeSql,
        },
      );
      if (body == null) {
        open?.({
          type: "error",
          message: t("catalog.sample.precision"),
        });
        return;
      }
      const data = await runObjectSample(object.id, body);
      setOffset(nextOffset);
      setResult(data);
      setApplied({
        limit,
        offset: nextOffset,
        filterKey,
        orderColumn,
        orderDirection,
        columnsKey,
        includeSql,
      });
      setForbidden(false);
    } catch (err) {
      if (err instanceof ApiError && err.status === 403) {
        setForbidden(true);
        setResult(null);
        setApplied(null);
        return;
      }
      open?.({
        type: "error",
        message: problemMessage(t, err, String(err)),
      });
    } finally {
      setRunning(false);
    }
  };

  return {
    canSamplePending,
    canSample,
    forbidden,
    limit,
    setLimit,
    offset,
    setOffset,
    filter,
    setFilter,
    filters,
    addFilter,
    removeFilter,
    updateFilter,
    clearFilters,
    selectedColumns,
    setSelectedColumns,
    includeSql,
    setIncludeSql,
    orderColumn,
    setOrderColumn,
    orderDirection,
    setOrderDirection,
    toggleSort,
    result,
    stale,
    unstableOrder,
    running,
    run,
  };
}
