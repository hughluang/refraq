"use client";

import {
  Badge,
  Button,
  Divider,
  Group,
  Modal,
  Stack,
  Switch,
  Table,
  Tabs,
  Text,
  Textarea,
  TextInput,
  Title,
  Tooltip,
  UnstyledButton,
} from "@mantine/core";
import { useForm } from "@mantine/form";
import { useCan, useNotification, useTranslate } from "@refinedev/core";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  forwardRef,
  useEffect,
  useImperativeHandle,
  useMemo,
  useRef,
  useState,
} from "react";

import { ConfirmActionModal } from "@/components/feedback/ConfirmActionModal";
import { EmptyState } from "@/components/feedback/EmptyState";
import { PageBodySkeleton } from "@/components/feedback/PageBodySkeleton";
import { PageError } from "@/components/feedback/PageError";
import { TextareaField } from "@/components/form/TextareaField";
import { TextField } from "@/components/form/TextField";
import { FillColumn } from "@/components/layout/FillColumn";
import { PageChrome } from "@/components/layout/PageChrome";
import {
  activateChannel,
  createChannel,
  deactivateChannel,
  deleteChannel,
  getChannel,
  getDraft,
  listNodeTypes,
  listVersions,
  patchChannel,
  previewPublish,
  publishChannel,
  saveDraft,
  validateDraft,
} from "@/features/channels/api";
import { ChannelCanvas, type CanvasFocus } from "@/features/channels/ChannelCanvas";
import type { Graph, GraphProblem } from "@/features/channels/types";
import { clientGraphProblems } from "@/features/channels/graphValidation";
import { ModuleAction, ModuleId } from "@/features/console/module-identity";
import { LEAVE_GUARD_ALLOW } from "@/hooks/leaveGuard";
import { useFormatInstant } from "@/hooks/useFormatInstant";
import { useLeaveGuard } from "@/hooks/useLeaveGuard";
import { ApiError } from "@/lib/api";
import { problemMessage } from "@/lib/problem";

import type { Channel, ChannelVersion, Confirmation, NodeTypeSpec } from "@/features/channels/types";

const FORM_ID = "channel-record-form";
const NAME_MAX = 200;
const DESCRIPTION_MAX = 2000;

type IdentityValues = {
  name: string;
  description: string;
  active: boolean;
};

class RecordInvalid extends Error {}

type Props =
  | { mode: "create" }
  | { mode: "show" | "edit"; channelId: string };

export function ChannelRecord(props: Props) {
  if (props.mode === "create") return <ChannelCreate />;
  return <ChannelExisting mode={props.mode} channelId={props.channelId} />;
}

function ChannelCreate() {
  const t = useTranslate();
  const { open } = useNotification();
  const [busy, setBusy] = useState(false);
  const form = useForm({ initialValues: { name: "", description: "" } });
  const leaveGuard = useLeaveGuard({
    enabled: form.isDirty(),
    message: t("common.leaveUnsaved"),
  });

  return (
    <PageChrome
      title={t("channels.create.title")}
      actions={
        <Group gap="xs" wrap="nowrap" aria-label={t("channels.actions.standard")}>
          <Button
            component={Link}
            href="/console/channels"
            variant="default"
            size="sm"
            data-leave-guard={LEAVE_GUARD_ALLOW}
          >
            {t("common.cancel")}
          </Button>
          <Button type="submit" form={FORM_ID} size="sm" loading={busy}>
            {t("channels.create.submit")}
          </Button>
        </Group>
      }
    >
      <form
        id={FORM_ID}
        onSubmit={form.onSubmit(async (values) => {
          setBusy(true);
          try {
            const description = values.description.trim();
            const created = await createChannel({
              name: values.name.trim(),
              description: description ? description : null,
            });
            form.resetDirty();
            leaveGuard.bypass();
            open?.({ type: "success", message: t("channels.create.success") });
            window.location.replace(`/console/channels/${created.channel.id}/edit`);
          } catch (error) {
            open?.({
              type: "error",
              message: problemMessage(t, error, t("channels.save.failed")),
            });
          } finally {
            setBusy(false);
          }
        })}
      >
        <IdentityFields form={form} editable />
      </form>
    </PageChrome>
  );
}

function ChannelExisting({
  mode,
  channelId,
}: {
  mode: "show" | "edit";
  channelId: string;
}) {
  const t = useTranslate();
  const router = useRouter();
  const { open } = useNotification();
  const formatInstant = useFormatInstant();
  const { data: canWrite } = useCan({
    resource: ModuleId.channels,
    action: ModuleAction.edit,
  });
  const [channel, setChannel] = useState<Channel | null>(null);
  const [graph, setGraph] = useState<Graph | null>(null);
  const [baseline, setBaseline] = useState("");
  const [revision, setRevision] = useState(1);
  const [versions, setVersions] = useState<ChannelVersion[]>([]);
  const [catalog, setCatalog] = useState<NodeTypeSpec[]>([]);
  const [problems, setProblems] = useState<GraphProblem[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);
  const [tab, setTab] = useState("canvas");
  const [preview, setPreview] = useState<Confirmation | null>(null);
  const [publishRevision, setPublishRevision] = useState(1);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [reloadToken, setReloadToken] = useState(0);
  const [focus, setFocus] = useState<CanvasFocus | null>(null);
  const [descriptionOpen, setDescriptionOpen] = useState(false);
  const [descriptionDraft, setDescriptionDraft] = useState("");
  const focusToken = useRef(0);
  const nameEditorRef = useRef<ChannelNameHeadingHandle>(null);
  const form = useForm<IdentityValues>({
    initialValues: { name: "", description: "", active: false },
    validate: {
      name: (value) => {
        const trimmed = value.trim();
        if (!trimmed) return t("channels.validation.name.required");
        if (trimmed.length > NAME_MAX) return t("channels.validation.name.length");
        return null;
      },
    },
  });
  const formRef = useRef(form);
  formRef.current = form;

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setLoadError(null);
    void Promise.all([
      getChannel(channelId),
      getDraft(channelId),
      listVersions(channelId, { limit: 50 }),
      listNodeTypes(),
    ])
      .then(([channelBody, draft, versionPage, types]) => {
        if (cancelled) return;
        setChannel(channelBody.channel);
        setGraph(draft.graph);
        setBaseline(JSON.stringify(draft.graph));
        setRevision(draft.draft_revision);
        setVersions(versionPage.items);
        setCatalog(types.items);
        formRef.current.setValues({
          name: channelBody.channel.name,
          description: channelBody.channel.description ?? "",
          active: channelBody.channel.active,
        });
        formRef.current.resetDirty();
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          setLoadError(error instanceof ApiError ? error : null);
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [channelId, reloadToken]);

  useEffect(() => {
    if (mode !== "edit" || canWrite?.can !== false) return;
    router.replace(`/console/channels/${channelId}`);
  }, [canWrite?.can, channelId, mode, router]);

  const writable = mode === "edit" && Boolean(canWrite?.can);
  const graphDirty = graph != null && JSON.stringify(graph) !== baseline;
  const unsaved = writable && (form.isDirty() || graphDirty);
  const leaveGuard = useLeaveGuard({
    enabled: writable && (form.isDirty() || graphDirty),
    message: t("common.leaveUnsaved"),
  });

  const entryTypes = useMemo(
    () => new Set(catalog.filter((item) => item.entry).map((item) => item.type)),
    [catalog],
  );
  const clientProblems = graph ? clientGraphProblems(graph, entryTypes) : [];
  const clientProblemRecords: GraphProblem[] = clientProblems.map((item) => ({
    code: item.code,
    node_id: item.nodeId,
    edge_id: item.edgeId,
    detail: "",
  }));
  const shownProblems = uniqueProblems([
    ...clientProblemRecords.filter((item) => item.node_id || item.edge_id),
    ...problems,
  ]);
  const problemNodeIds = new Set(
    [...problems, ...clientProblemRecords]
      .map((item) => item.node_id)
      .filter((id): id is string => Boolean(id)),
  );
  const problemEdgeIds = new Set(
    [...problems, ...clientProblemRecords]
      .map((item) => item.edge_id)
      .filter((id): id is string => Boolean(id)),
  );

  const focusProblem = (problem: GraphProblem) => {
    if (!problem.node_id && !problem.edge_id) return;
    focusToken.current += 1;
    setFocus({
      token: focusToken.current,
      nodeId: problem.node_id,
      edgeId: problem.node_id ? null : problem.edge_id,
    });
  };

  const notifyError = (error: unknown) => {
    open?.({
      type: "error",
      message:
        error instanceof RecordInvalid
          ? error.message
          : problemMessage(t, error, t("channels.save.failed")),
    });
  };

  const persist = async (): Promise<number> => {
    let nextRevision = revision;
    const nameError = nameEditorRef.current?.commit() ?? null;
    if (nameError) {
      throw new RecordInvalid(nameError);
    }
    const pendingName = form.getValues().name.trim();
    if (!pendingName || pendingName.length > NAME_MAX) {
      const message = pendingName
        ? t("channels.validation.name.length")
        : t("channels.validation.name.required");
      nameEditorRef.current?.showError(message);
      throw new RecordInvalid(message);
    }
    if (form.isDirty()) {
      const values = form.getValues();
      const description = values.description.trim();
      const descriptionValue = description ? description : null;
      let saved = channel;
      if (
        saved &&
        (values.name.trim() !== saved.name ||
          descriptionValue !== (saved.description ?? null))
      ) {
        const updated = await patchChannel(channelId, {
          name: values.name.trim(),
          description: descriptionValue,
        });
        saved = updated.channel;
        setChannel(saved);
      }
      if (saved && values.active !== saved.active) {
        const updated = values.active
          ? await activateChannel(channelId)
          : await deactivateChannel(channelId);
        saved = updated.channel;
        setChannel(saved);
      }
      form.resetDirty(values);
    }
    if (graph && JSON.stringify(graph) !== baseline) {
      const saved = await saveDraft(channelId, {
        base_revision: nextRevision,
        graph,
      });
      nextRevision = saved.draft_revision;
      setRevision(saved.draft_revision);
      setGraph(saved.graph);
      setBaseline(JSON.stringify(saved.graph));
    }
    return nextRevision;
  };

  if (loading) return <PageBodySkeleton />;
  if (loadError || !channel || !graph) {
    return (
      <PageError
        message={problemMessage(t, loadError, t("channels.load.failed"))}
        requestId={loadError?.requestId}
        onRetry={() => setReloadToken((value) => value + 1)}
      />
    );
  }
  if (mode === "edit" && canWrite?.can === false) return <PageBodySkeleton />;

  const showEdit = mode === "show" && Boolean(canWrite?.can);
  const showLifecycle = Boolean(canWrite?.can);

  const descriptionText = form.values.description.trim();
  const descriptionLabel = writable
    ? descriptionText
      ? t("channels.description.edit")
      : t("channels.description.add")
    : t("channels.description.view");
  const openDescription = () => {
    setDescriptionDraft(form.values.description);
    setDescriptionOpen(true);
  };
  const closeDescription = () => setDescriptionOpen(false);
  const applyDescription = () => {
    form.setFieldValue("description", descriptionDraft.trim());
    setDescriptionOpen(false);
  };

  return (
    <PageChrome
      title={form.values.name || channel.name}
      titleSlot={
        <ChannelNameHeading
          ref={nameEditorRef}
          key={`${channel.id}:${channel.updated_at}`}
          name={form.values.name}
          editable={writable && !busy}
          onCommit={(name) => form.setFieldValue("name", name)}
        />
      }
      titleExtra={
        <>
          <ChannelActiveStatus
            active={form.values.active}
            editable={writable && !busy}
            onToggle={() => form.setFieldValue("active", !form.values.active)}
          />
          {unsaved ? (
            <Badge variant="dot" color="orange" size="sm" tt="none">
              {t("channels.unsaved")}
            </Badge>
          ) : null}
          {writable || descriptionText ? (
            <Button
              variant="subtle"
              size="compact-sm"
              color="gray"
              disabled={busy}
              onClick={openDescription}
            >
              {descriptionLabel}
            </Button>
          ) : null}
        </>
      }
      description={descriptionText || undefined}
      descriptionLineClamp={2}
      actions={
        <Group gap="xs" wrap="wrap" align="center">
          <Group gap="xs" wrap="nowrap" aria-label={t("channels.actions.navigation")}>
            <Button
              component={Link}
              href="/console/channels"
              variant="subtle"
              size="sm"
              data-leave-guard={LEAVE_GUARD_ALLOW}
            >
              {t("channels.actions.back")}
            </Button>
          </Group>
          {showLifecycle ? (
            <>
              <Divider orientation="vertical" h={28} />
              <Group gap="xs" wrap="nowrap" aria-label={t("channels.actions.lifecycle")}>
                <Button
                  size="sm"
                  variant="default"
                  loading={busy}
                  onClick={() => {
                    setBusy(true);
                    void persist()
                      .then(() => validateDraft(channelId))
                      .then((result) => {
                        setProblems(result.problems);
                        setTab("canvas");
                        open?.({
                          type: result.valid ? "success" : "error",
                          message: result.valid
                            ? t("channels.validate.ok")
                            : t("channels.validate.failed"),
                        });
                      })
                      .catch(notifyError)
                      .finally(() => setBusy(false));
                  }}
                >
                  {t("channels.actions.validate")}
                </Button>
                <Button
                  size="sm"
                  variant={mode === "show" ? "filled" : "light"}
                  loading={busy}
                  onClick={() => {
                    setBusy(true);
                    void persist()
                      .then(async (nextRevision) => {
                        setPublishRevision(nextRevision);
                        setPreview(await previewPublish(channelId));
                      })
                      .catch(notifyError)
                      .finally(() => setBusy(false));
                  }}
                >
                  {t("channels.actions.publish")}
                </Button>
              </Group>
            </>
          ) : null}
          {showEdit || canWrite?.can || writable ? (
            <>
          <Divider orientation="vertical" h={28} />
          <Group gap="xs" wrap="nowrap" aria-label={t("channels.actions.standard")}>
            {showEdit ? (
              <Button
                component={Link}
                href={`/console/channels/${channelId}/edit`}
                size="sm"
                variant="light"
              >
                {t("actions.edit")}
              </Button>
            ) : null}
            {canWrite?.can ? (
              <Button
                size="sm"
                color="red"
                variant="light"
                onClick={() => setConfirmDelete(true)}
              >
                {t("actions.delete")}
              </Button>
            ) : null}
            {writable ? (
              <Button
                component={Link}
                href={`/console/channels/${channelId}`}
                variant="default"
                size="sm"
                data-leave-guard={LEAVE_GUARD_ALLOW}
              >
                {t("common.cancel")}
              </Button>
            ) : null}
            {writable ? (
              <Button
                type="submit"
                form={FORM_ID}
                size="sm"
                loading={busy}
              >
                {t("channels.edit.submit")}
              </Button>
            ) : null}
          </Group>
            </>
          ) : null}
        </Group>
      }
    >
      <form
        id={FORM_ID}
        hidden
        onSubmit={(event) => {
          event.preventDefault();
          setBusy(true);
          void persist()
            .then(() => {
              open?.({ type: "success", message: t("channels.edit.success") });
            })
            .catch(notifyError)
            .finally(() => setBusy(false));
        }}
      />
      <FillColumn>
      <Tabs
        value={tab}
        onChange={(value) => setTab(value ?? "canvas")}
        keepMounted
        style={{
          flex: 1,
          minHeight: 0,
          display: "flex",
          flexDirection: "column",
        }}
        styles={{
          panel: {
            flex: 1,
            minHeight: 0,
            overflow: "auto",
            display: "flex",
            flexDirection: "column",
          },
        }}
      >
        <Tabs.List>
          <Tabs.Tab value="canvas">{t("channels.tabs.canvas")}</Tabs.Tab>
          <Tabs.Tab value="versions">{t("channels.tabs.versions")}</Tabs.Tab>
        </Tabs.List>
        <Tabs.Panel value="canvas" pt="md" style={{ overflow: "hidden" }}>
          <ChannelCanvas
            key={baseline}
            graph={graph}
            catalog={catalog}
            editable={writable}
            problems={shownProblems}
            problemNodeIds={problemNodeIds}
            problemEdgeIds={problemEdgeIds}
            focus={focus}
            onChange={setGraph}
            onFocusProblem={focusProblem}
          />
        </Tabs.Panel>
        <Tabs.Panel value="versions" pt="md">
          {versions.length === 0 ? (
            <EmptyState message={t("channels.versions.empty")} />
          ) : (
            <Table>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>{t("channels.versions.number")}</Table.Th>
                  <Table.Th>{t("channels.versions.publisher")}</Table.Th>
                  <Table.Th>{t("channels.versions.publishedAt")}</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {versions.map((version) => (
                  <Table.Tr key={version.number}>
                    <Table.Td>{version.number}</Table.Td>
                    <Table.Td>{version.published_by_name ?? "—"}</Table.Td>
                    <Table.Td>{formatInstant(version.published_at)}</Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          )}
        </Tabs.Panel>
      </Tabs>
      </FillColumn>
      <Modal
        opened={descriptionOpen}
        onClose={closeDescription}
        title={t("channels.fields.description")}
      >
        {writable ? (
          <Stack gap="sm">
            <Text size="sm" c="dimmed">
              {t("channels.description.hint")}
            </Text>
            <Textarea
              aria-label={t("channels.fields.description")}
              placeholder={t("channels.description.optional")}
              value={descriptionDraft}
              autosize
              minRows={3}
              maxRows={12}
              onChange={(event) =>
                setDescriptionDraft(event.currentTarget.value.slice(0, DESCRIPTION_MAX))
              }
            />
            <Group justify="flex-end">
              <Button variant="default" onClick={closeDescription}>
                {t("common.cancel")}
              </Button>
              <Button onClick={applyDescription}>{t("channels.description.apply")}</Button>
            </Group>
          </Stack>
        ) : (
          <Stack gap="sm">
            <Text size="sm" style={{ whiteSpace: "pre-wrap" }}>
              {descriptionText || t("channels.description.empty")}
            </Text>
            <Group justify="flex-end">
              <Button variant="default" onClick={closeDescription}>
                {t("channels.description.close")}
              </Button>
            </Group>
          </Stack>
        )}
      </Modal>
      <ConfirmActionModal
        opened={preview != null}
        onClose={() => setPreview(null)}
        title={t("channels.publish.title")}
        confirmLabel={t("channels.publish.confirm")}
        loading={busy}
        onConfirm={() => {
          setBusy(true);
          void publishChannel(channelId, publishRevision)
            .then(async () => {
              setPreview(null);
              setProblems([]);
              leaveGuard.bypass();
              open?.({ type: "success", message: t("channels.publish.done") });
              setReloadToken((value) => value + 1);
            })
            .catch(notifyError)
            .finally(() => setBusy(false));
        }}
      >
        <Stack gap="xs">
          <Text size="sm">{t("channels.publish.mirrors")}</Text>
          <Text size="sm" c="dimmed">
            {preview && preview.mirrors_to_open.length > 0
              ? preview.mirrors_to_open.map((item) => item.locator).join(", ")
              : t("channels.publish.mirrorsEmpty")}
          </Text>
          <Text size="sm">{t("channels.publish.runs")}</Text>
          <Text size="sm" c="dimmed">
            {preview && preview.runs_to_cancel.length > 0
              ? preview.runs_to_cancel.map((item) => item.job_id).join(", ")
              : t("channels.publish.runsEmpty")}
          </Text>
          {preview?.missing_run_timeout ? (
            <Text size="sm" c="orange">
              {t("channels.publish.missingTimeout")}
            </Text>
          ) : null}
        </Stack>
      </ConfirmActionModal>
      <ConfirmActionModal
        opened={confirmDelete}
        onClose={() => setConfirmDelete(false)}
        title={t("channels.delete.title")}
        confirmLabel={t("actions.delete")}
        confirmColor="red"
        loading={busy}
        onConfirm={() => {
          setBusy(true);
          void deleteChannel(channelId)
            .then(() => {
              leaveGuard.bypass();
              window.location.replace("/console/channels");
            })
            .catch((error) => {
              notifyError(error);
              setBusy(false);
            });
        }}
      />
    </PageChrome>
  );
}

type ChannelNameHeadingHandle = {
  commit: () => string | null;
  showError: (message: string) => void;
};

const ChannelNameHeading = forwardRef<
  ChannelNameHeadingHandle,
  {
    name: string;
    editable: boolean;
    onCommit: (name: string) => void;
  }
>(function ChannelNameHeading({ name, editable, onCommit }, ref) {
  const t = useTranslate();
  const inputRef = useRef<HTMLInputElement>(null);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(name);
  const [error, setError] = useState<string | null>(null);
  const editingRef = useRef(false);
  const draftRef = useRef(name);
  editingRef.current = editing;
  draftRef.current = draft;

  useEffect(() => {
    if (!editing) setDraft(name);
  }, [editing, name]);

  useEffect(() => {
    if (!editing) return;
    inputRef.current?.focus();
    inputRef.current?.select();
  }, [editing]);

  const finish = (raw: string): string | null => {
    if (!editingRef.current) return null;
    const next = raw.trim();
    if (!next) {
      const message = t("channels.validation.name.required");
      setError(message);
      setEditing(true);
      return message;
    }
    if (next.length > NAME_MAX) {
      const message = t("channels.validation.name.length");
      setError(message);
      setEditing(true);
      return message;
    }
    editingRef.current = false;
    onCommit(next);
    setDraft(next);
    setError(null);
    setEditing(false);
    return null;
  };

  useImperativeHandle(ref, () => ({
    commit: () => finish(draftRef.current),
    showError: (message: string) => {
      editingRef.current = true;
      setError(message);
      setEditing(true);
    },
  }));

  if (!editable) {
    return <Title order={2}>{name}</Title>;
  }

  if (!editing) {
    return (
      <Title order={2}>
        <Tooltip label={t("channels.name.edit")}>
          <UnstyledButton
            onClick={() => {
              setDraft(name);
              setError(null);
              editingRef.current = true;
              setEditing(true);
            }}
            style={{
              font: "inherit",
              color: "inherit",
              textAlign: "left",
              cursor: "pointer",
              textDecoration: "underline",
              textDecorationStyle: "dotted",
              textUnderlineOffset: "0.15em",
            }}
          >
            {name}
          </UnstyledButton>
        </Tooltip>
      </Title>
    );
  }

  return (
    <TextInput
      ref={inputRef}
      aria-label={t("channels.fields.name")}
      value={draft}
      error={error}
      description={error ? t("channels.name.revert") : undefined}
      maxLength={NAME_MAX}
      w={360}
      onChange={(event) => {
        const value = event.currentTarget.value;
        draftRef.current = value;
        setDraft(value);
        if (error && value.trim()) setError(null);
      }}
      onBlur={() => {
        finish(draftRef.current);
      }}
      onKeyDown={(event) => {
        if (event.key === "Enter") {
          event.preventDefault();
          finish(draftRef.current);
        }
        if (event.key === "Escape") {
          event.preventDefault();
          editingRef.current = false;
          setDraft(name);
          setError(null);
          setEditing(false);
        }
      }}
      styles={{
        input: {
          fontWeight: 700,
          fontSize: "var(--mantine-h2-font-size)",
        },
      }}
    />
  );
});

function ChannelActiveStatus({
  active,
  editable,
  onToggle,
}: {
  active: boolean;
  editable: boolean;
  onToggle: () => void;
}) {
  const t = useTranslate();
  if (!editable) {
    const label = active ? t("channels.status.active") : t("channels.status.inactive");
    return (
      <Badge variant="light" color={active ? "green" : "gray"} size="sm" tt="none">
        {label}
      </Badge>
    );
  }
  return (
    <Switch
      size="sm"
      label={t("channels.fields.active")}
      checked={active}
      disabled={!editable}
      onChange={onToggle}
      styles={{ body: { alignItems: "center" } }}
    />
  );
}

function IdentityFields({
  form,
  editable,
}: {
  form: ReturnType<typeof useForm<{ name: string; description: string }>>;
  editable: boolean;
}) {
  const t = useTranslate();
  return (
    <Stack>
      <TextField
        editable={editable}
        label={t("channels.fields.name")}
        required={editable}
        {...form.getInputProps("name")}
      />
      <TextareaField
        editable={editable}
        label={t("channels.fields.description")}
        {...form.getInputProps("description")}
      />
    </Stack>
  );
}

function uniqueProblems(items: GraphProblem[]): GraphProblem[] {
  const seen = new Set<string>();
  return items.filter((item) => {
    const key = `${item.code}|${item.node_id ?? ""}|${item.edge_id ?? ""}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}
