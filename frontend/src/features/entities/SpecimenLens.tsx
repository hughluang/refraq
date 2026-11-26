"use client";

import {
  ActionIcon,
  Badge,
  Button,
  CloseButton,
  Group,
  Menu,
  Select,
  Stack,
  Switch,
  Table,
  Text,
  Tooltip,
  UnstyledButton,
} from "@mantine/core";
import { useTranslate } from "@refinedev/core";

import { RecordPicker } from "@/components/form/RecordPicker";
import { userRecordAdapter } from "@/components/form/recordPickerAdapters";
import {
  BanIcon,
  CheckIcon,
  EyeOffIcon,
  KeyIcon,
  PencilIcon,
  RepeatIcon,
  UserIcon,
} from "@/components/icons";
import { presentCell, withheldNames } from "@/features/entities/accessLogic";
import {
  effectiveCeilingForColumn,
  formatMaskSample,
  type NarrowSelection,
  type SpecimenPin,
  type WorkbenchIntent,
  type WorkbenchSelection,
} from "@/features/entities/accessWorkbench";
import type { AccessSummary, PreviewAccessResponse } from "@/features/entities/accessTypes";
import { attributeTitle } from "@/features/entities/entityPresentation";

import classes from "./AccessWorkbench.module.css";

type Props = {
  summary: AccessSummary;
  pin: SpecimenPin;
  selection: WorkbenchSelection;
  preview: PreviewAccessResponse | null;
  previewBusy: boolean;
  canPreviewRows: boolean;
  busyId: string | null;
  dispatch: (intent: WorkbenchIntent) => Promise<boolean>;
};

export function SpecimenLens({
  summary,
  pin,
  selection,
  preview,
  previewBusy,
  canPreviewRows,
  busyId,
  dispatch,
}: Props) {
  const t = useTranslate();
  const ladders = summary.ladders;
  const profiles = summary.profiles;

  const narrowOptions = [
    { value: "none", label: t("entities.access.workbench.narrowAll") },
    ...(preview?.identities ?? []).map((item) => ({
      value: item.type === "user" ? "user" : `${item.type}:${item.id ?? ""}`,
      label: `${t(`entities.access.subject.${item.type}`)}: ${item.display_name}`,
    })),
  ];

  const currentNarrowValue =
    pin.kind !== "user" || pin.narrow.kind === "none"
      ? "none"
      : pin.narrow.kind === "user"
        ? "user"
        : `${pin.narrow.kind}:${pin.narrow.id}`;

  const parseNarrow = (val: string | null): NarrowSelection => {
    if (!val || val === "none") return { kind: "none" };
    if (val === "user") return { kind: "user" };
    const [kind, id] = val.split(":");
    if ((kind === "role" || kind === "group") && id) return { kind, id };
    return { kind: "none" };
  };

  return (
    <div className={classes.lensFrame}>
      <div className={classes.lensToolbar}>
        <Group gap="xs" wrap="wrap">
          {pin.kind === "profiles" ? (
            <>
              <Text size="sm" fw={600}>
                {t("entities.access.workbench.lensMatrixTitle")}
              </Text>
              <Badge size="xs" variant="light">
                {profiles.length} × {ladders.length}
              </Badge>
            </>
          ) : (
            <>
              <Badge size="md" variant="light" leftSection={<UserIcon size={12} />}>
                {pin.displayName}
              </Badge>
              <Select
                size="xs"
                aria-label={t("entities.access.workbench.narrowLabel")}
                data={narrowOptions}
                value={currentNarrowValue}
                allowDeselect={false}
                onChange={(val) =>
                  void dispatch({ kind: "set_narrow", narrow: parseNarrow(val) })
                }
              />
              <Switch
                size="xs"
                label={t("entities.access.preview.includeRows")}
                checked={pin.includeRows && canPreviewRows}
                disabled={!canPreviewRows || previewBusy}
                onChange={(e) =>
                  void dispatch({
                    kind: "set_include_rows",
                    includeRows: e.currentTarget.checked,
                  })
                }
              />
              <ActionIcon
                size="sm"
                variant="subtle"
                loading={previewBusy}
                aria-label={t("jobs.refresh")}
                onClick={() => void dispatch({ kind: "refresh_preview" })}
              >
                <RepeatIcon size={14} />
              </ActionIcon>
              <CloseButton
                size="sm"
                aria-label={t("entities.access.workbench.backToMatrix")}
                onClick={() => void dispatch({ kind: "pin_profiles" })}
              />
            </>
          )}
        </Group>

        <Group gap="xs" wrap="nowrap">
          <div style={{ minWidth: 190 }}>
            <RecordPicker
              editable
              aria-label={t("entities.access.preview")}
              placeholder={t("entities.access.workbench.inspectUserPlaceholder")}
              adapter={userRecordAdapter()}
              value={pin.kind === "user" ? pin.userId : null}
              onChange={(userId) => {
                if (!userId) {
                  void dispatch({ kind: "pin_profiles" });
                  return;
                }
                void dispatch({
                  kind: "pin_user",
                  userId,
                  displayName: userId,
                  includeRows: canPreviewRows,
                });
              }}
            />
          </div>
          {pin.kind === "profiles" ? (
            <Button
              size="xs"
              variant="default"
              onClick={() => void dispatch({ kind: "select", selection: { kind: "profile_copy" } })}
            >
              {t("entities.access.profiles.copy")}
            </Button>
          ) : null}
        </Group>
      </div>

      <Table.ScrollContainer minWidth={600}>
        <Table verticalSpacing="xs" horizontalSpacing="sm" highlightOnHover>
          <Table.Thead>
            <Table.Tr>
              <Table.Th style={{ minWidth: 140 }}>
                {pin.kind === "profiles"
                  ? t("entities.access.profiles")
                  : t("entities.access.preview.rows")}
              </Table.Th>
              {ladders.map((ladder) => {
                const { denied, ceilingLevel } = effectiveCeilingForColumn(
                  summary.restrictions,
                  ladder.attribute_id,
                );
                const isSelected =
                  selection?.kind === "ladder" && selection.attributeId === ladder.attribute_id;
                return (
                  <Table.Th key={ladder.attribute_id} style={{ minWidth: 150 }}>
                    <UnstyledButton
                      className={classes.colHeaderBtn}
                      onClick={() =>
                        void dispatch({
                          kind: "select",
                          selection: { kind: "ladder", attributeId: ladder.attribute_id },
                        })
                      }
                    >
                      <Group justify="space-between" wrap="nowrap" gap={4}>
                        <Group gap={4} wrap="nowrap" style={{ minWidth: 0 }}>
                          {ladder.business_key ? <KeyIcon size={12} /> : null}
                          <Text size="xs" fw={isSelected ? 700 : 600} truncate>
                            {attributeTitle({
                              name: ladder.attribute_name,
                              display_name: ladder.attribute_display_name,
                            })}
                          </Text>
                        </Group>
                        <Group gap={3} wrap="nowrap">
                          {denied ? (
                            <Tooltip label={t("entities.access.workbench.columnDenied")}>
                              <span>
                                <EyeOffIcon size={12} />
                              </span>
                            </Tooltip>
                          ) : null}
                          {ceilingLevel ? (
                            <Tooltip
                              label={t("entities.access.workbench.columnCapped", {
                                level: ceilingLevel,
                              })}
                            >
                              <Badge size="xs" color="orange" variant="light">
                                ≤ {ceilingLevel}
                              </Badge>
                            </Tooltip>
                          ) : null}
                          <Badge size="xs" variant="outline">
                            {ladder.levels.length}
                          </Badge>
                        </Group>
                      </Group>
                      <Text size="xs" c="dimmed" truncate>
                        {ladder.attribute_name} · {ladder.type}
                      </Text>
                    </UnstyledButton>
                  </Table.Th>
                );
              })}
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {ladders.length === 0 ? (
              <Table.Tr>
                <Table.Td colSpan={1}>
                  <Text size="sm" c="dimmed" py="md" ta="center">
                    {t("entities.access.ladders.empty")}
                  </Text>
                </Table.Td>
              </Table.Tr>
            ) : pin.kind === "profiles" ? (
              profiles.length === 0 ? (
                <Table.Tr>
                  <Table.Td colSpan={ladders.length + 1}>
                    <Text size="sm" c="dimmed" py="md" ta="center">
                      {t("entities.access.profiles.empty")}
                    </Text>
                  </Table.Td>
                </Table.Tr>
              ) : (
                profiles.map((profile) => {
                  const selected =
                    selection?.kind === "profile" && selection.id === profile.id;
                  return (
                    <Table.Tr key={profile.id}>
                      <Table.Td>
                        <UnstyledButton
                          onClick={() =>
                            void dispatch({
                              kind: "select",
                              selection: { kind: "profile", id: profile.id },
                            })
                          }
                        >
                          <Stack gap={2}>
                            <Text size="sm" fw={selected ? 700 : 600}>
                              {profile.name}
                            </Text>
                            <Text size="xs" c="dimmed">
                              {profile.key}
                            </Text>
                          </Stack>
                        </UnstyledButton>
                      </Table.Td>
                      {ladders.map((ladder) => {
                        const col = profile.columns.find(
                          (c) => c.attribute_id === ladder.attribute_id,
                        );
                        const levelObj = col
                          ? ladder.levels.find((l) => l.key === col.level)
                          : undefined;
                        const sample = levelObj
                          ? formatMaskSample(ladder, levelObj.mode)
                          : null;

                        return (
                          <Table.Td key={ladder.attribute_id}>
                            <Menu position="bottom-start" withinPortal>
                              <Menu.Target>
                                <UnstyledButton
                                  className={`${classes.swatchCell} ${!col ? classes.withheldCell : ""}`}
                                  style={{ width: "100%" }}
                                  disabled={busyId !== null}
                                  aria-label={`${profile.name} ${ladder.attribute_name}`}
                                >
                                  {col && levelObj ? (
                                    <Stack gap={1}>
                                      <Text size="xs" fw={500} truncate>
                                        {sample}
                                      </Text>
                                      <Text size="xs" c="dimmed" truncate>
                                        {levelObj.key === "clear"
                                          ? t("entities.access.mask.clear")
                                          : `${t(`entities.access.mask.${typeof levelObj.mode === "string" ? levelObj.mode : levelObj.mode.type}`)} (${levelObj.key})`}
                                      </Text>
                                    </Stack>
                                  ) : (
                                    <Text size="xs" c="dimmed">
                                      {t("entities.access.profiles.notInProfile")}
                                    </Text>
                                  )}
                                </UnstyledButton>
                              </Menu.Target>
                              <Menu.Dropdown>
                                <Menu.Item
                                  leftSection={!col ? <CheckIcon size={12} /> : <BanIcon size={12} />}
                                  onClick={() =>
                                    void dispatch({
                                      kind: "set_profile_cell",
                                      profileId: profile.id,
                                      attributeId: ladder.attribute_id,
                                      level: "",
                                    })
                                  }
                                >
                                  {t("entities.access.profiles.notInProfile")}
                                </Menu.Item>
                                {ladder.levels.map((level) => {
                                  const active = col?.level === level.key;
                                  const modeKind =
                                    typeof level.mode === "string" ? level.mode : level.mode.type;
                                  return (
                                    <Menu.Item
                                      key={level.key}
                                      leftSection={active ? <CheckIcon size={12} /> : undefined}
                                      rightSection={
                                        <Text size="xs" c="dimmed">
                                          {formatMaskSample(ladder, level.mode)}
                                        </Text>
                                      }
                                      onClick={() =>
                                        void dispatch({
                                          kind: "set_profile_cell",
                                          profileId: profile.id,
                                          attributeId: ladder.attribute_id,
                                          level: level.key,
                                        })
                                      }
                                    >
                                      {level.key === "clear"
                                        ? t("entities.access.mask.clear")
                                        : `${t(`entities.access.mask.${modeKind}`)} (${level.key})`}
                                    </Menu.Item>
                                  );
                                })}
                              </Menu.Dropdown>
                            </Menu>
                          </Table.Td>
                        );
                      })}
                    </Table.Tr>
                  );
                })
              )
            ) : (
              <>
                {/* Authoritative User Shape Row */}
                <Table.Tr>
                  <Table.Td>
                    <Text size="xs" fw={600} c="dimmed">
                      {t("entities.access.preview.columns")}
                    </Text>
                  </Table.Td>
                  {ladders.map((ladder) => {
                    const attr = preview?.schema.attributes.find(
                      (a) => a.name === ladder.attribute_name,
                    );
                    if (!attr) {
                      return (
                        <Table.Td key={ladder.attribute_id} className={classes.withheldCell}>
                          <Text size="xs" c="dimmed">
                            {t("entities.access.profiles.notInProfile")}
                          </Text>
                        </Table.Td>
                      );
                    }
                    const topLevel = attr.presentation?.levels?.[0];
                    const sample = topLevel
                      ? formatMaskSample(
                          ladder,
                          topLevel.mode as Parameters<typeof formatMaskSample>[1],
                        )
                      : null;
                    return (
                      <Table.Td key={ladder.attribute_id}>
                        <Stack gap={2}>
                          {sample ? (
                            <Text size="xs" fw={500} truncate>
                              {sample}
                            </Text>
                          ) : null}
                          <Group gap={4} wrap="wrap">
                            {attr.writable ? (
                              <Badge size="xs" variant="light" leftSection={<PencilIcon size={10} />}>
                                {t("entities.access.action.write")}
                              </Badge>
                            ) : null}
                            {attr.presentation?.row_varying ? (
                              <Badge size="xs" variant="outline">
                                {t("entities.access.cell.rowVarying")}
                              </Badge>
                            ) : null}
                            {attr.presentation?.may_be_withheld ? (
                              <Badge size="xs" color="orange" variant="outline">
                                {t("entities.access.cell.withheld")}
                              </Badge>
                            ) : null}
                          </Group>
                        </Stack>
                      </Table.Td>
                    );
                  })}
                </Table.Tr>

                {/* Authoritative User Data Rows */}
                {(preview?.rows?.items ?? []).map((row, rowIndex) => {
                  const held = withheldNames(row, preview?.schema.withheld_field ?? null);
                  const sourcesMap =
                    row.__sources && typeof row.__sources === "object"
                      ? (row.__sources as Record<string, unknown>)
                      : {};
                  return (
                    <Table.Tr key={rowIndex}>
                      <Table.Td>
                        <Text size="xs" c="dimmed">
                          #{rowIndex + 1}
                        </Text>
                      </Table.Td>
                      {ladders.map((ladder) => {
                        const attr = preview?.schema.attributes.find(
                          (a) => a.name === ladder.attribute_name,
                        );
                        if (!attr) {
                          return (
                            <Table.Td key={ladder.attribute_id} className={classes.withheldCell}>
                              <Text size="xs" c="dimmed">
                                —
                              </Text>
                            </Table.Td>
                          );
                        }
                        const cell = presentCell({
                          name: attr.name,
                          value: row[attr.name],
                          withheld: held,
                          referenceHidden: false,
                        });
                        const rawSources = sourcesMap[attr.name];
                        const sources = Array.isArray(rawSources)
                          ? rawSources.filter((s): s is string => typeof s === "string")
                          : [];
                        const isWithheld = cell.kind === "withheld";
                        return (
                          <Table.Td
                            key={ladder.attribute_id}
                            className={isWithheld ? classes.withheldCell : undefined}
                            onMouseEnter={() =>
                              void dispatch({
                                kind: "hover",
                                hover: {
                                  kind: "cell",
                                  rowIndex,
                                  attributeName: attr.name,
                                  sources,
                                  withheld: isWithheld,
                                },
                              })
                            }
                            onMouseLeave={() => void dispatch({ kind: "hover", hover: null })}
                          >
                            <Text size="xs" c={cell.kind === "value" ? undefined : "dimmed"} truncate>
                              {isWithheld
                                ? t("entities.access.cell.withheld")
                                : cell.kind === "empty"
                                  ? t("entities.access.cell.empty")
                                  : cell.text}
                            </Text>
                          </Table.Td>
                        );
                      })}
                    </Table.Tr>
                  );
                })}
              </>
            )}
          </Table.Tbody>
        </Table>
      </Table.ScrollContainer>
    </div>
  );
}
