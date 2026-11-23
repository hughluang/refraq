"use client";

import { Button, Stack, Text } from "@mantine/core";
import { useTranslate } from "@refinedev/core";
import { useEffect, useRef, useState } from "react";
import { DisplayField } from "@/components/display/DisplayField";
import { Instant } from "@/components/display/Instant";
import { Instant as ContractInstant } from "@/lib/instant";
import { presentProblemNotification } from "@/components/feedback/presentProblemNotification";
import { getJournalPage } from "./api";
import type { JournalEvent, JournalPage, MirrorDetail } from "./types";
import styles from "./MirrorCopySummary.module.css";

export function EventResult({ event }: { event: JournalEvent }) {
  const t = useTranslate();
  return <>
    {event.outcome && <span>{t(`mirrors.journal.${event.outcome}`)}
      {event.outcome_at && <> · <Instant value={event.outcome_at} /></>}
      {event.related_operation_id && <> · <code>{event.related_operation_id}</code></>}
    </span>}
  </>;
}

export function Receipt({ event }: { event?: JournalEvent | null }) {
  const t = useTranslate();
  if (!event) return <>{t("mirrors.unknownEvidence")}</>;
  return <Stack gap={2}>
    <span>{t(`mirrors.journal.${event.kind}`)} · <Instant value={event.at} /></span>
    {event.outcome && <EventResult event={event} />}
  </Stack>;
}

export function MirrorJournal({ mirror }: { mirror: MirrorDetail }) {
  const t = useTranslate();
  const [older, setOlder] = useState<JournalPage | null>(null);
  const [busy, setBusy] = useState(false);
  const flight = useRef<AbortController | null>(null);
  useEffect(() => () => flight.current?.abort(), []);
  const first = mirror.journal;
  if (!first) return null;
  const cursor = older ? older.next_cursor : first.next_cursor;
  const events = [...first.items, ...(older?.items ?? [])];
  const days = new Map<string, JournalEvent[]>();
  for (const event of events) {
    const timestamp = ContractInstant.epochMsOf(event.at);
    const day = timestamp === null ? t("mirrors.unknownEvidence") : new Date(timestamp).toISOString().slice(0, 10) + " UTC";
    const group = days.get(day) ?? [];
    group.push(event);
    days.set(day, group);
  }
  async function more() {
    if (!cursor || flight.current) return;
    const controller = new AbortController();
    flight.current = controller;
    setBusy(true);
    try {
      const page = await getJournalPage(mirror.id, cursor, controller.signal);
      if (!controller.signal.aborted) setOlder({ ...page, items: [...(older?.items ?? []), ...page.items] });
    } catch (error) {
      if (!controller.signal.aborted) presentProblemNotification(t, error);
    } finally {
      if (!controller.signal.aborted) setBusy(false);
      flight.current = null;
    }
  }
  return <section aria-label={t("mirrors.journalTitle")} className={styles.journal}>
    <h2>{t("mirrors.journalTitle")}</h2>
    {events.length === 0 && <Text size="sm">{t("mirrors.unknownEvidence")}</Text>}
    {Array.from(days, ([day, items]) => <div key={day}>
      <h3>{day}</h3>
      <ol>{items.map(event => <li key={event.id}>
        <Text size="xs" c="dimmed">{t(`mirrors.journal.${event.category}`)} · <Instant value={event.at} /></Text>
        <Text fw={600} size="sm">{t(`mirrors.journal.${event.kind}`)}</Text>
        {event.outcome && <Text size="sm"><EventResult event={event} /></Text>}
      </li>)}</ol>
    </div>)}
    {cursor && <Button size="xs" variant="subtle" loading={busy} onClick={() => void more()}>{t("mirrors.journal.older")}</Button>}
    <details>
      <summary>{t("mirrors.identifiers")}</summary>
      <div className={styles.identifiers}>
        <DisplayField label={t("mirrors.mirrorId")} value={mirror.id} />
        <DisplayField label={t("mirrors.operationId")} value={mirror.latest_request?.operation_id} />
        <DisplayField label={t("mirrors.revision")} value={mirror.control.control_revision} />
        <DisplayField label={t("mirrors.epoch")} value={mirror.history_epoch} />
      </div>
      {events.map(event => <div key={event.id} className={styles.eventIds}>
        <strong>{t(`mirrors.journal.${event.kind}`)} · <Instant value={event.at} /></strong>
        <div className={styles.identifiers}>
          <DisplayField label={t("mirrors.operationId")} value={event.operation_id} />
          <DisplayField label={t("mirrors.revision")} value={event.control_revision} />
          <DisplayField label={t("mirrors.epoch")} value={event.history_epoch} />
          <DisplayField label={t("mirrors.eventGeneration")} value={event.generation_id} />
        </div>
      </div>)}
    </details>
  </section>;
}
