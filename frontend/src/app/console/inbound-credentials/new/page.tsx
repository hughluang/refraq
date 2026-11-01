"use client";

import { Suspense } from "react";

import { PageBodySkeleton } from "@/components/feedback/PageBodySkeleton";
import { InboundCredentialRecord } from "@/features/inbound-credentials/InboundCredentialRecord";

export default function InboundCredentialCreatePage() {
  return (
    <Suspense fallback={<PageBodySkeleton />}>
      <InboundCredentialRecord mode="create" />
    </Suspense>
  );
}
