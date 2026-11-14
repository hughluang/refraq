"use client";

import { Button, Drawer, Group, Stack, Text, UnstyledButton } from "@mantine/core";
import { useTranslate } from "@refinedev/core";
import { useEffect, useRef, useState } from "react";
import { StatusBadge } from "@/components/display/StatusBadge";
import { NumberField } from "@/components/form/NumberField";
import { presentProblemNotification } from "@/components/feedback/presentProblemNotification";
import { ConsoleLink } from "@/components/navigation/ConsoleLink";
import { getJoinPath } from "@/features/sources/api/joins";
import type { JoinPathResult } from "@/features/sources/types";

type PathState =
  | { status: "loading" }
  | { status: "unloaded"; hops: number }
  | { status: "ready"; result: JoinPathResult };

export function RelationPathsDrawer({ start, onClose }: { start: string; onClose: () => void }) {
  const t = useTranslate();
  const [maxHops, setMaxHops] = useState<number | string>(2);
  const [state, setState] = useState<PathState>({ status: "loading" });
  const generation = useRef(0);
  const active = useRef(false);
  const inFlight = useRef(false);

  async function load(hops: number) {
    if (!active.current || inFlight.current) return;
    const request = ++generation.current;
    inFlight.current = true;
    setState({ status: "loading" });
    try {
      const result = await getJoinPath({ start, max_hops: hops, top_targets: 10 });
      if (active.current && request === generation.current) setState({ status: "ready", result });
    } catch (error) {
      if (!active.current || request !== generation.current) return;
      setState({ status: "unloaded", hops });
      presentProblemNotification(t, error, {
        onRetry: () => {
          if (active.current && request === generation.current) void load(hops);
        },
      });
    } finally {
      if (request === generation.current) inFlight.current = false;
    }
  }

  useEffect(() => {
    active.current = true;
    void load(2);
    return () => {
      active.current = false;
      generation.current += 1;
      inFlight.current = false;
    };
  }, [start]);

  const validHops = typeof maxHops === "number" && Number.isInteger(maxHops) && maxHops >= 1 && maxHops <= 5;

  return (
    <Drawer opened onClose={onClose} title={t("catalog.joins.path.title")} position="right" size="md">
      <Stack gap="md">
        <form onSubmit={(event) => {
          event.preventDefault();
          if (typeof maxHops === "number" && validHops) void load(maxHops);
        }}>
          <Group gap="sm" align="flex-end">
            <NumberField
              editable
              label={t("catalog.joins.path.maxHops")}
              value={maxHops}
              onChange={setMaxHops}
              min={1}
              max={5}
              allowDecimal={false}
              w={140}
            />
            <Button type="submit" variant="light" loading={state.status === "loading"} disabled={!validHops}>
              {t("catalog.joins.path.explore")}
            </Button>
          </Group>
        </form>
        {state.status === "loading" ? (
          <Text role="status" size="sm" c="dimmed">{t("catalog.joins.path.loading")}</Text>
        ) : state.status === "unloaded" ? (
          <UnstyledButton
            type="button"
            aria-label={t("common.retry")}
            onClick={() => void load(state.hops)}
          >
            <StatusBadge tone="danger" labelKey="status.unloaded" />
          </UnstyledButton>
        ) : (
          <Stack gap="sm">
            <Text size="xs" c="dimmed">{t("catalog.joins.path.traversalDirection")}</Text>
            {state.result.paths.length === 0 ? (
              <Text size="sm" c="dimmed">{t("catalog.joins.path.empty")}</Text>
            ) : state.result.paths.map((path, index) => (
              <Stack
                key={`${path.target_object_id ?? "target"}-${index}`}
                gap={4}
                p="sm"
                style={{
                  border: "1px solid var(--refraq-tone-neutral-border)",
                  borderRadius: "var(--mantine-radius-md)",
                  overflowWrap: "anywhere",
                }}
              >
                <Text size="sm" fw={500}>
                  {t("catalog.joins.path.summary")}: {path.path_summary}
                </Text>
                {path.hops.map((hop, hopIndex) => (
                  <Text key={`${hop.join_id}-${hopIndex}`} size="xs" c="dimmed">
                    {hop.from_column_locator_key ?? hop.from_column_id} → {hop.to_column_locator_key ?? hop.to_column_id} ({hop.join_kind})
                  </Text>
                ))}
                {path.target_object_id ? (
                  <Button
                    component={ConsoleLink}
                    href={`/console/catalog/${encodeURIComponent(path.target_object_id)}`}
                    size="xs"
                    variant="light"
                    w="fit-content"
                  >
                    {t("catalog.joins.path.openTarget")}
                  </Button>
                ) : null}
              </Stack>
            ))}
          </Stack>
        )}
      </Stack>
    </Drawer>
  );
}
