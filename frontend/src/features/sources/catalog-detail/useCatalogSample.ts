"use client";

import { useCan, useNotification } from "@refinedev/core";
import { useEffect, useMemo, useState } from "react";

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
} from "@/features/sources/catalog-detail/sampleFilters";
import type { CatalogObject, SampleResult } from "@/features/sources/types";
import { ApiError } from "@/lib/api";

const DEFAULT_FILTER: SampleFilter = {
  column: null,
  op: "eq",
  value: "",
};

export const DEFAULT_SAMPLE_LIMIT = 50;

export function useCatalogSample(object: CatalogObject) {
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

  const [limit, setLimit] = useState(DEFAULT_SAMPLE_LIMIT);
  const [offset, setOffset] = useState(0);
  const [filter, setFilter] = useState<SampleFilter>(DEFAULT_FILTER);
  const [orderColumn, setOrderColumn] = useState<string | null>(() =>
    defaultSampleOrderColumn(object),
  );
  const [orderDirection, setOrderDirection] = useState<"asc" | "desc">("asc");
  const [result, setResult] = useState<SampleResult | null>(null);
  const [applied, setApplied] = useState<SampleAppliedParams | null>(null);
  const [forbidden, setForbidden] = useState(false);
  const [running, setRunning] = useState(false);

  useEffect(() => {
    setLimit(DEFAULT_SAMPLE_LIMIT);
    setOffset(0);
    setFilter(DEFAULT_FILTER);
    setOrderColumn(defaultSampleOrderColumn(object));
    setOrderDirection("asc");
    setResult(null);
    setApplied(null);
    setForbidden(false);
  }, [object.id]);

  const filterKey = useMemo(() => sampleFilterSnapshot(filter), [filter]);
  const currentParams: SampleAppliedParams = {
    limit,
    offset,
    filterKey,
    orderColumn,
    orderDirection,
  };
  const stale = Boolean(result) && isSampleStale(applied, currentParams);
  const unstableOrder = isUnstableOrder(offset, orderColumn);

  const run = async (nextOffset: number = offset) => {
    if (!isSampleEligible(object.object_type)) {
      return;
    }
    setRunning(true);
    try {
      const data = await runObjectSample(
        object.id,
        buildSampleRequest(
          filter,
          orderColumn,
          orderDirection,
          nextOffset,
          limit,
        ),
      );
      setOffset(nextOffset);
      setResult(data);
      setApplied({
        limit,
        offset: nextOffset,
        filterKey,
        orderColumn,
        orderDirection,
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
        message: err instanceof ApiError ? err.detail : String(err),
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
    orderColumn,
    setOrderColumn,
    orderDirection,
    setOrderDirection,
    result,
    stale,
    unstableOrder,
    running,
    run,
  };
}
