"use client";

import { Suspense } from "react";
import { useParams } from "next/navigation";

import { PageBodySkeleton } from "@/components/feedback/PageBodySkeleton";
import { InboundCredentialRecord } from "@/features/inbound-credentials/InboundCredentialRecord";

export default function InboundCredentialDetailPage() {
  const params = useParams<{ id: string }>();
  return (
    <Suspense fallback={<PageBodySkeleton />}>
      <InboundCredentialRecord mode="show" credentialId={params.id} />
    </Suspense>
  );
}
