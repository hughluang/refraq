"use client";

import { Suspense } from "react";

import { PageBodySkeleton } from "@/components/feedback/PageBodySkeleton";
import { WebhookRecord } from "@/features/webhooks/WebhookRecord";

export default function WebhookCreatePage() {
  return (
    <Suspense fallback={<PageBodySkeleton />}>
      <WebhookRecord mode="create" />
    </Suspense>
  );
}
