"use client";

import { Suspense } from "react";
import { useParams } from "next/navigation";

import { PageBodySkeleton } from "@/components/feedback/PageBodySkeleton";
import { WebhookRecord } from "@/features/webhooks/WebhookRecord";

export default function WebhookDetailPage() {
  const params = useParams<{ id: string }>();
  return (
    <Suspense fallback={<PageBodySkeleton />}>
      <WebhookRecord mode="show" webhookId={params.id} />
    </Suspense>
  );
}
