"use client";

import {
  Badge,
  Box,
  Button,
  Divider,
  Drawer,
  Group,
  Modal,
  Stack,
  Switch,
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
  useRef,
  useState,
} from "react";

import { ConfirmActionModal } from "@/components/feedback/ConfirmActionModal";
import { PageBodySkeleton } from "@/components/feedback/PageBodySkeleton";
import { PageError } from "@/components/feedback/PageError";
import { NumberField } from "@/components/form/NumberField";
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
  getRun,
  listNodeTypes,
  listRuns,
  patchChannel,
  previewPublish,
  previewTemplate,
  publishChannel,
  saveDraft,
  startRun,
  validateDraft,
  type DraftValidation,
} from "@/features/channels/api";
import { ChannelCanvas } from "@/features/channels/ChannelCanvas";
import { isTerminalRun, recordedKey } from "@/features/channels/runSession";
import type { ChannelTemplatePreview } from "@/features/channels/TemplateRunPreview";
import { ChannelRuns } from "@/features/channels/ChannelRuns";
import { ChannelVersions } from "@/features/channels/ChannelVersions";
import type { ExpressionContext, Graph, GraphProblem, RefinedPort } from "@/features/channels/types";
import {
  graphWithoutUnsetIntegers,
  validationContentKey,
  validationDelay,
  refusedProblems,
  validationResultApplies,
} from "@/features/channels/graphValidation";
import { formatGraphProblem } from "@/features/channels/problemLabel";
import { ModuleAction, ModuleId } from "@/features/console/module-identity";
import { LEAVE_GUARD_ALLOW } from "@/hooks/leaveGuard";
import { useLeaveGuard } from "@/hooks/useLeaveGuard";
import { ApiError } from "@/lib/api";
import { problemMessage } from "@/lib/problem";

import type { Channel, ChannelRunDetail, Confirmation, NodeTypeSpec } from "@/features/channels/types";
import { cancelJob } from "@/features/jobs/api";

const FORM_ID = "channel-record-form";
const NAME_MAX = 200;
const DESCRIPTION_MAX = 2000;

function runTimeoutSec(value: number | string): number | null {
  return typeof value === "number" && value > 0 ? Math.floor(value) : null;
}

type IdentityValues = {
  name: string;
  description: string;
  active: boolean;
};

class RecordInvalid extends Error {}

type DraftAccess = "browse" | "edit" | "locked";

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
  const { data: canWrite } = useCan({
    resource: ModuleId.channels,
    action: ModuleAction.edit,
  });
  const { data: canJobs } = useCan({
    resource: ModuleId.jobs,
    action: ModuleAction.list,
  });
  const [channel, setChannel] = useState<Channel | null>(null);
  const [graph, setGraph] = useState<Graph | null>(null);
  const [baseline, setBaseline] = useState("");
  const [revision, setRevision] = useState(1);
  const [catalog, setCatalog] = useState<NodeTypeSpec[]>([]);
  const [problems, setProblems] = useState<GraphProblem[]>([]);
  const [ports, setPorts] = useState<RefinedPort[]>([]);
  const [expressionContext, setExpressionContext] = useState<ExpressionContext | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);
  const [panel, setPanel] = useState<"versions" | "runs" | null>(null);
  const [preview, setPreview] = useState<Confirmation | null>(null);
  const [publishRevision, setPublishRevision] = useState(1);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [reloadToken, setReloadToken] = useState(0);
  const [descriptionOpen, setDescriptionOpen] = useState(false);
  const [runRequest, setRunRequest] = useState<{ stopAt: string | null } | null>(null);
  const [sessionRun, setSessionRun] = useState<ChannelRunDetail | null>(null);
  const [adoptToken, setAdoptToken] = useState(0);
  const [descriptionDraft, setDescriptionDraft] = useState("");
  const [timeoutDraft, setTimeoutDraft] = useState<number | string>("");
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
  const validateSeq = useRef(0);
  const loadedChannelRef = useRef<string | null>(null);
  const arrivalRef = useRef(false);
  const runEpoch = useRef(0);
  const [draftEpoch, setDraftEpoch] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setLoadError(null);
    loadedChannelRef.current = null;
    validateSeq.current += 1;
    setProblems([]);
    setPorts([]);
    setExpressionContext(null);
    const epoch = ++runEpoch.current;
    setSessionRun(null);
    void listRuns(channelId, { target: "draft", limit: 1 })
      .then((page) => {
        const latest = page.items[0];
        if (!latest || cancelled || runEpoch.current !== epoch) return null;
        return getRun(channelId, latest.job_id);
      })
      .then((detail) => {
        if (!detail || cancelled || runEpoch.current !== epoch) return;
        setSessionRun(detail);
      })
      .catch((error: unknown) => {
        if (cancelled || runEpoch.current !== epoch) return;
        open?.({
          type: "error",
          message: problemMessage(t, error, t("channels.load.failed")),
        });
      });
    void Promise.all([getChannel(channelId), getDraft(channelId), listNodeTypes()])
      .then(([channelBody, draft, types]) => {
        if (cancelled) return;
        loadedChannelRef.current = channelId;
        arrivalRef.current = true;
        setChannel(channelBody.channel);
        setGraph(graphWithoutUnsetIntegers(draft.graph, types.items));
        setDraftEpoch((epoch) => epoch + 1);
        setBaseline(JSON.stringify(draft.graph));
        setRevision(draft.draft_revision);
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
  const runActive = sessionRun != null && !isTerminalRun(sessionRun.run.status);
  const draftAccess: DraftAccess = !writable ? "browse" : runActive ? "locked" : "edit";
  const draftEditable = draftAccess === "edit";
  const canStop = Boolean(canWrite?.can || canJobs?.can);
  const runJobId = sessionRun?.run.job_id ?? null;
  const runStatus = sessionRun?.run.status ?? null;
  useEffect(() => {
    if (!runJobId || runStatus == null || isTerminalRun(runStatus)) return;
    const timer = window.setInterval(() => {
      void getRun(channelId, runJobId)
        .then(setSessionRun)
        .catch(() => undefined);
    }, 2000);
    return () => window.clearInterval(timer);
  }, [channelId, runJobId, runStatus]);
  const graphDirty = graph != null && JSON.stringify(graph) !== baseline;
  const leaveGuard = useLeaveGuard({
    enabled: writable && (form.isDirty() || graphDirty),
    message: t("common.leaveUnsaved"),
  });

  const notifyError = (error: unknown) => {
    open?.({
      type: "error",
      message:
        error instanceof RecordInvalid
          ? error.message
          : problemMessage(t, error, t("channels.save.failed")),
    });
  };

  const graphRef = useRef(graph);
  graphRef.current = graph;
  const contentKey = graph ? validationContentKey(graph) : "";
  const scheduleRef = useRef({ content: "", delay: 0 });
  if (
    graph &&
    loadedChannelRef.current === channelId &&
    (arrivalRef.current || scheduleRef.current.content !== contentKey)
  ) {
    const opened = arrivalRef.current;
    arrivalRef.current = false;
    scheduleRef.current = {
      content: contentKey,
      delay: validationDelay(opened),
    };
  }

  useEffect(() => {
    const current = graphRef.current;
    if (canWrite?.can !== true || !current) return;
    if (loadedChannelRef.current !== channelId) return;
    const seq = ++validateSeq.current;
    const delay = scheduleRef.current.delay;
    const timer = window.setTimeout(() => {
      void validateDraft(channelId, current)
        .then((result) => {
          if (validateSeq.current !== seq) return;
          setProblems(result.problems);
          setPorts(result.ports);
          setExpressionContext(result.context);
        })
        .catch((error: unknown) => {
          if (validateSeq.current !== seq) return;
          notifyError(error);
        });
    }, delay);
    return () => window.clearTimeout(timer);
  }, [canWrite?.can, channelId, contentKey, draftEpoch]);

  const reportBlockedGraph = (
    result: DraftValidation,
    source: Graph,
    blocking: GraphProblem[] = [],
  ) => {
    // A run or publish check can resolve after the canvas has moved on.
    // Applying that snapshot would replace the problems on screen and drop the newer check.
    if (!validationResultApplies(source, graphRef.current)) return;
    validateSeq.current += 1;
    setProblems(result.problems);
    setPorts(result.ports);
    setExpressionContext(result.context);
    setPanel(null);
    const firstError =
      blocking[0] ?? result.problems.find((problem) => problem.severity !== "warning");
    open?.({
      type: "error",
      message: firstError
        ? t("channels.validate.failedWith", {
            problem: formatGraphProblem(t, firstError, source),
          })
        : t("channels.validate.failed"),
    });
  };

  const revealInvalidGraph = (error: unknown) => {
    if (!(error instanceof ApiError) || error.code !== "CHANNEL_GRAPH_INVALID" || !graph) {
      return null;
    }
    setPreview(null);
    setRunRequest(null);
    const blocking = refusedProblems(error);
    return validateDraft(channelId, graph).then((result) =>
      reportBlockedGraph(result, graph, blocking),
    );
  };

  const catchFailure = (error: unknown) => {
    const revealed = revealInvalidGraph(error);
    if (revealed) return revealed.catch(notifyError);
    notifyError(error);
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

  const persist = async (draftGraph?: Graph): Promise<{ revision: number; graph: Graph }> => {
    let nextRevision = revision;
    let nextGraph = draftGraph ?? graph;
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
        values.name.trim() !== saved.name ||
        descriptionValue !== (saved.description ?? null)
      ) {
        const updated = await patchChannel(channelId, {
          name: values.name.trim(),
          description: descriptionValue,
        });
        saved = updated.channel;
        setChannel(saved);
      }
      if (values.active !== saved.active) {
        const updated = values.active
          ? await activateChannel(channelId)
          : await deactivateChannel(channelId);
        saved = updated.channel;
        setChannel(saved);
      }
      form.resetDirty(values);
    }
    if (JSON.stringify(nextGraph) !== baseline) {
      const saved = await saveDraft(channelId, {
        base_revision: nextRevision,
        graph: nextGraph,
      });
      nextRevision = saved.draft_revision;
      nextGraph = graphWithoutUnsetIntegers(saved.graph, catalog);
      setRevision(saved.draft_revision);
      setGraph(nextGraph);
      setBaseline(JSON.stringify(nextGraph));
      setAdoptToken((token) => token + 1);
    }
    return { revision: nextRevision, graph: nextGraph };
  };

  const rememberRun = async (jobId: string) => {
    const epoch = ++runEpoch.current;
    const detail = await getRun(channelId, jobId);
    if (runEpoch.current !== epoch) return;
    setSessionRun(detail);
  };

  const openRun = (stopAt: string | null) => {
    setRunRequest({ stopAt });
  };

  const templatePreview: ChannelTemplatePreview | null = canWrite?.can
    ? {
        run: sessionRun
          ? {
              key: recordedKey(sessionRun),
              evaluate: (nodeId, path) =>
                previewTemplate(channelId, sessionRun.run.job_id, {
                  graph,
                  node_id: nodeId,
                  path,
                }),
            }
          : null,
      }
    : null;

  const launch = () => {
    const stopAt = runRequest?.stopAt ?? null;
    if (!graph || runActive) return;
    const triggers = graph.nodes.filter((node) => node.type.startsWith("trigger."));
    if (triggers.length !== 1) {
      notifyError(new Error(t("channels.run.needTrigger")));
      return;
    }
    setBusy(true);
    void (async () => {
      await persist();
      const started = await startRun(channelId, {
        target: "draft",
        ignore_checkpoints: false,
        stop_at_node_id: stopAt,
      });
      await rememberRun(started.run.job_id);
      setRunRequest(null);
    })()
      .catch(catchFailure)
      .finally(() => setBusy(false));
  };

  const stopRun = () => {
    if (!sessionRun) return;
    const jobId = sessionRun.run.job_id;
    setBusy(true);
    void cancelJob(jobId)
      .then(() => getRun(channelId, jobId))
      .then(setSessionRun)
      .catch(catchFailure)
      .finally(() => setBusy(false));
  };

  const runStopAt = runRequest?.stopAt ?? null;
  const runNode = runStopAt ? graph.nodes.find((node) => node.id === runStopAt) : undefined;
  const runNodeName = runNode ? runNode.name || runNode.ref : null;

  const showEdit = mode === "show" && Boolean(canWrite?.can);
  const showLifecycle = Boolean(canWrite?.can);

  const descriptionText = form.values.description.trim();
  const versionLabel = channel.latest_version
    ? `v${channel.latest_version.number}`
    : t("channels.versions.unpublished");
  const togglePanel = (next: "versions" | "runs") => {
    setPanel((current) => (current === next ? null : next));
  };
  const openDescription = () => {
    setDescriptionDraft(form.values.description);
    setTimeoutDraft(graph.settings.run_timeout_sec ?? "");
    setDescriptionOpen(true);
  };
  const closeDescription = () => setDescriptionOpen(false);
  const applyDescription = () => {
    form.setFieldValue("description", descriptionDraft.trim());
    const next = runTimeoutSec(timeoutDraft);
    setGraph((current) =>
      current
        ? { ...current, settings: { ...current.settings, run_timeout_sec: next } }
        : current,
    );
    setDescriptionOpen(false);
  };

  return (
    // Above app chrome (100/101) and below modal (200) and popover (300).
    <Box
      flex={1}
      h="100%"
      mih={0}
      style={{
        position: "relative",
        zIndex: 150,
        display: "flex",
        flexDirection: "column",
        overflow: "hidden",
      }}
    >
    <PageChrome
      fill
      title={form.values.name || channel.name}
      titleSlot={
        <ChannelNameHeading
          ref={nameEditorRef}
          key={`${channel.id}:${channel.updated_at.toJSON()}`}
          name={form.values.name}
          editable={draftEditable && !busy}
          onCommit={(name) => form.setFieldValue("name", name)}
        />
      }
      titleExtra={
        <>
          <ChannelActiveStatus
            active={form.values.active}
            editable={draftEditable && !busy}
            onToggle={() => form.setFieldValue("active", !form.values.active)}
          />
          <Group gap={4} wrap="nowrap">
            <Button
              variant="subtle"
              size="compact-sm"
              color="gray"
              disabled={busy}
              aria-expanded={panel === "versions"}
              aria-label={t("channels.versions.open", { version: versionLabel })}
              leftSection={<StackedPagesIcon />}
              onClick={() => togglePanel("versions")}
            >
              {versionLabel}
            </Button>
            <Button
              variant="subtle"
              size="compact-sm"
              color="gray"
              disabled={busy}
              aria-expanded={panel === "runs"}
              leftSection={<ListIcon />}
              onClick={() => togglePanel("runs")}
            >
              {t("channels.tabs.runs")}
            </Button>
            <Button
              variant="subtle"
              size="compact-sm"
              color="gray"
              disabled={busy}
              leftSection={<SlidersIcon />}
              onClick={openDescription}
            >
              {t("channels.details.title")}
            </Button>
          </Group>
        </>
      }
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
            {writable ? (
              <Button
                size="sm"
                variant="filled"
                loading={busy}
                disabled={!draftEditable}
                onClick={() => openRun(null)}
              >
                {t("channels.run.open")}
              </Button>
            ) : null}
            {runActive && canStop ? (
              <Button size="sm" color="red" variant="light" loading={busy} onClick={stopRun}>
                {t("channels.run.stop")}
              </Button>
            ) : null}
          </Group>
          {showLifecycle ? (
            <>
              <Divider orientation="vertical" h={28} />
              <Group gap="xs" wrap="nowrap" aria-label={t("channels.actions.lifecycle")}>
                <Button
                  size="sm"
                  variant={mode === "show" ? "filled" : "light"}
                  loading={busy}
                  disabled={draftAccess === "locked"}
                  onClick={() => {
                    setBusy(true);
                    void persist()
                      .then(async ({ revision: nextRevision, graph: savedGraph }) => {
                        const result = await validateDraft(channelId, savedGraph);
                        if (!result.valid) {
                          reportBlockedGraph(result, savedGraph);
                          return;
                        }
                        if (!validationResultApplies(savedGraph, graphRef.current)) return;
                        validateSeq.current += 1;
                        setProblems(result.problems);
                        setPorts(result.ports);
                        setExpressionContext(result.context);
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
                disabled={!draftEditable}
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
        <ChannelCanvas
          key={draftEpoch}
          channelId={channelId}
          graph={graph}
          catalog={catalog}
          appearance={writable ? "edit" : "browse"}
          mutable={draftEditable}
          adoptToken={adoptToken}
          problems={problems}
          ports={ports}
          context={expressionContext}
          onChange={setGraph}
          sessionRun={sessionRun}
          templatePreview={templatePreview}
          onRun={openRun}
          onPersistForTest={async (screenGraph) => {
            await persist(screenGraph);
          }}
        />
      </FillColumn>
      <Modal
        opened={runRequest != null}
        onClose={() => setRunRequest(null)}
        title={runNodeName != null ? t("channels.run.upTo", { node: runNodeName }) : t("channels.run.open")}
      >
        <Stack gap="sm">
          <Text size="sm">
            {runNodeName != null
              ? t("channels.run.writesUpTo", { node: runNodeName })
              : t("channels.run.writes")}
          </Text>
          <Group justify="flex-end">
            <Button variant="default" disabled={busy} onClick={() => setRunRequest(null)}>
              {t("common.cancel")}
            </Button>
            <Button loading={busy} onClick={() => launch()}>
              {t("channels.run.confirm")}
            </Button>
          </Group>
        </Stack>
      </Modal>
      <Modal
        opened={descriptionOpen}
        onClose={closeDescription}
        title={t("channels.details.title")}
      >
        {draftEditable ? (
          <Stack gap="sm">
            <Text size="sm" c="dimmed">
              {t("channels.description.hint")}
            </Text>
            <Textarea
              label={t("channels.fields.description")}
              placeholder={t("channels.description.optional")}
              value={descriptionDraft}
              autosize
              minRows={3}
              maxRows={12}
              onChange={(event) =>
                setDescriptionDraft(event.currentTarget.value.slice(0, DESCRIPTION_MAX))
              }
            />
            <NumberField
              editable
              label={t("channels.settings.runTimeout")}
              description={t("channels.settings.runTimeoutHint")}
              min={1}
              w={280}
              value={timeoutDraft}
              onChange={setTimeoutDraft}
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
            <Stack gap={4}>
              <Text size="sm" fw={500}>
                {t("channels.fields.description")}
              </Text>
              <Text size="sm" style={{ whiteSpace: "pre-wrap" }}>
                {descriptionText || t("channels.description.empty")}
              </Text>
            </Stack>
            <NumberField
              editable={false}
              label={t("channels.settings.runTimeout")}
              description={t("channels.settings.runTimeoutHint")}
              w={280}
              value={graph.settings.run_timeout_sec ?? ""}
            />
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
              setPorts([]);
              setExpressionContext(null);
              leaveGuard.bypass();
              open?.({ type: "success", message: t("channels.publish.done") });
              setReloadToken((value) => value + 1);
            })
            .catch(catchFailure)
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
    <Box
      className="channel-record-overlays"
      pos="absolute"
      inset={0}
      style={{ zIndex: 20, pointerEvents: "none" }}
    >
      <Drawer
        opened={panel === "versions"}
        onClose={() => setPanel(null)}
        position="right"
        size="xl"
        withinPortal={false}
        withOverlay={false}
        lockScroll={false}
        trapFocus={false}
        zIndex={20}
        title={t("channels.tabs.versions")}
      >
        {panel === "versions" ? (
          <ChannelVersions channelId={channelId} reloadToken={reloadToken} />
        ) : null}
      </Drawer>
      <Drawer
        opened={panel === "runs"}
        onClose={() => setPanel(null)}
        position="right"
        size="xl"
        withinPortal={false}
        withOverlay={false}
        lockScroll={false}
        trapFocus={false}
        zIndex={20}
        title={t("channels.tabs.runs")}
      >
        {panel === "runs" ? <ChannelRuns channelId={channelId} /> : null}
      </Drawer>
    </Box>
    </Box>
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

function StackedPagesIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 16 16" aria-hidden="true">
      <rect x="3" y="4.5" width="8" height="8.5" rx="1" fill="none" stroke="currentColor" strokeWidth="1.5" />
      <path d="M5 3.25h8.25A.75.75 0 0 1 14 4v8" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
    </svg>
  );
}

function ListIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 16 16" aria-hidden="true">
      <path d="M3 4.5h10M3 8h10M3 11.5h10" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
    </svg>
  );
}

function SlidersIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 16 16" aria-hidden="true">
      <path d="M2.5 4.5h11M2.5 11.5h11" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
      <circle cx="6" cy="4.5" r="1.6" fill="none" stroke="currentColor" strokeWidth="1.5" />
      <circle cx="10" cy="11.5" r="1.6" fill="none" stroke="currentColor" strokeWidth="1.5" />
    </svg>
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
