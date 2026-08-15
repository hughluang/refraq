"use client";

import { useParams } from "next/navigation";

import { SourceSchedulesPage } from "@/features/schedules/SourceSchedulesPage";

export default function SourceRelatedSchedulesPage() {
  const params = useParams<{ id: string }>();
  return <SourceSchedulesPage sourceId={params.id} />;
}
