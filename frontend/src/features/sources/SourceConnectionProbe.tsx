"use client";

import { Button, Group } from "@mantine/core";
import { useNotification, useTranslate } from "@refinedev/core";
import { useLayoutEffect, useRef, useState } from "react";

import { StatusBadge } from "@/components/display/StatusBadge";
import { testSource, testSourceDraft } from "@/features/sources/api/sources";
import type { Engine, SourceAccess } from "@/features/sources/types";

type Props = {
  sourceId?: string;
  engine: Engine;
  draft?: SourceAccess;
  disabled: boolean;
  validateDraft: () => boolean;
};

export function SourceConnectionProbe({ sourceId, engine, draft, disabled, validateDraft }: Props) {
  const t = useTranslate();
  const { open } = useNotification();
  const generation = useRef(0);
  const [status, setStatus] = useState<"testing" | "reachable" | "failed" | null>(null);

  // Mantine clones access when an unrelated form field changes.
  const testedSettings = JSON.stringify(draft);
  useLayoutEffect(() => {
    setStatus(null);
    return () => { generation.current += 1; };
  }, [sourceId, engine, testedSettings]);

  async function test() {
    if (draft && !validateDraft()) return;
    const attempt = ++generation.current;
    setStatus("testing");
    try {
      const result = sourceId
        ? await testSource(sourceId, draft ? { engine, access: draft } : {})
        : await testSourceDraft({ engine, access: draft! });
      if (attempt !== generation.current) return;
      setStatus(result.ok ? "reachable" : "failed");
      if (result.ok) {
        open?.({ type: "success", message: t("sources.test.success") });
      } else {
        open?.({
          type: "error",
          message: t(result.code === "SOURCE_TEST_TIMEOUT" ? "sources.workflow.timeout" : "sources.workflow.checkSettings"),
        });
      }
    } catch {
      if (attempt !== generation.current) return;
      setStatus("failed");
      open?.({ type: "error", message: t("sources.workflow.probeUnavailable") });
    }
  }

  return (
    <Group gap="sm" align="center">
      <Button type="button" size="sm" variant="light" disabled={disabled} loading={status === "testing"} onClick={() => void test()}>
        {t("sources.test")}
      </Button>
      <span role="status" aria-live="polite">
        {status === "testing" && <StatusBadge tone="running" labelKey="sources.workflow.testing" />}
        {status === "reachable" && <StatusBadge tone="success" labelKey="sources.test.success" />}
        {status === "failed" && <StatusBadge tone="danger" labelKey="sources.test.failed" />}
      </span>
    </Group>
  );
}
