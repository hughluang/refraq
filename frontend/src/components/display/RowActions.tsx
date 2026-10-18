"use client";

import { ActionIcon, Box, Button, Group, Menu, Tooltip } from "@mantine/core";
import { useTranslate } from "@refinedev/core";
import type { ComponentType, ReactNode } from "react";

import type { ActionSafety, ConsoleMutation } from "@/components/feedback/consoleAction";
import { useConsoleMutation } from "@/components/feedback/useConsoleMutation";
import { DotsIcon } from "@/components/icons";

const INLINE_LIMIT = 2;

type RowActionBase = {
  key: string;
  label: string;
  icon?: ComponentType<{ size?: number | string }>;
  /** Destructive verbs pass `"red"`. Size and variant are fixed. */
  color?: string;
  disabledReason?: string;
  hidden?: boolean;
};

/** A verb declares safety on `action` or, for a plain click, on `safety`. */
export type RowActionVerb =
  | (RowActionBase & { action: ConsoleMutation; onClick?: never })
  | (RowActionBase & {
      onClick: () => void;
      safety: ActionSafety;
      action?: never;
    });

export type RowActionsProps = {
  recordName: string;
  verbs: readonly RowActionVerb[];
};

function isActionVerb(
  verb: RowActionVerb,
): verb is Extract<RowActionVerb, { action: ConsoleMutation }> {
  return "action" in verb && verb.action != null;
}

function withReason(reason: string | undefined, node: ReactNode) {
  if (!reason) return node;
  return (
    <Tooltip label={reason}>
      <Box component="span" style={{ display: "inline-flex" }}>
        {node}
      </Box>
    </Tooltip>
  );
}

function VerbIcon({ verb }: { verb: RowActionVerb }) {
  if (!verb.icon) return null;
  const Icon = verb.icon;
  return <Icon size={14} />;
}

function InlineVerb({
  verb,
  loading,
  onRun,
}: {
  verb: RowActionVerb;
  loading: boolean;
  onRun: () => void;
}) {
  return withReason(
    verb.disabledReason,
    <Button
      type="button"
      size="xs"
      variant="light"
      color={verb.color}
      disabled={Boolean(verb.disabledReason)}
      loading={loading}
      leftSection={verb.icon ? <VerbIcon verb={verb} /> : undefined}
      onClick={onRun}
    >
      {verb.label}
    </Button>,
  );
}

export function RowActions({ recordName, verbs }: RowActionsProps) {
  const t = useTranslate();
  const mutation = useConsoleMutation();
  const visible = verbs.filter((verb) => !verb.hidden);
  if (visible.length === 0) return null;
  const inline = visible.slice(0, INLINE_LIMIT);
  const overflow = visible.slice(INLINE_LIMIT);

  function run(verb: RowActionVerb) {
    if (verb.disabledReason) return;
    if (isActionVerb(verb)) {
      mutation.run({ ...verb.action, key: verb.key });
      return;
    }
    verb.onClick();
  }

  return (
    <>
      <Group gap="xs" wrap="nowrap" justify="flex-end">
        {inline.map((verb) => (
          <InlineVerb
            key={verb.key}
            verb={verb}
            loading={mutation.isSubmitting(verb.key)}
            onRun={() => run(verb)}
          />
        ))}
        {overflow.length > 0 ? (
          <Menu position="bottom-end">
            <Menu.Target>
              <ActionIcon
                variant="subtle"
                size="sm"
                aria-label={t("common.rowActions.more", { record: recordName })}
              >
                <DotsIcon />
              </ActionIcon>
            </Menu.Target>
            <Menu.Dropdown>
              {overflow.map((verb) => (
                <Tooltip key={verb.key} label={verb.disabledReason} disabled={!verb.disabledReason}>
                  <Box>
                    <Menu.Item
                      color={verb.color}
                      disabled={Boolean(verb.disabledReason) || mutation.isSubmitting(verb.key)}
                      leftSection={verb.icon ? <VerbIcon verb={verb} /> : undefined}
                      onClick={() => run(verb)}
                    >
                      {verb.label}
                    </Menu.Item>
                  </Box>
                </Tooltip>
              ))}
            </Menu.Dropdown>
          </Menu>
        ) : null}
      </Group>
      {mutation.dialog}
    </>
  );
}
