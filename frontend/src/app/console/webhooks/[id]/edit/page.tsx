"use client";

import { Suspense } from "react";
import { useParams } from "next/navigation";

import { PageBodySkeleton } from "@/components/feedback/PageBodySkeleton";
import { WebhookRecord } from "@/features/webhooks/WebhookRecord";

export default function WebhookEditPage() {
  const params = useParams<{ id: string }>();
  return (
    <Suspense fallback={<PageBodySkeleton />}>
      <WebhookRecord mode="edit" webhookId={params.id} />
    </Suspense>
  );
}
