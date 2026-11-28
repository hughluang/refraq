"use client";

import { Suspense } from "react";
import { useParams } from "next/navigation";

import { PageBodySkeleton } from "@/components/feedback/PageBodySkeleton";
import { OAuthClientRecord } from "@/features/oauth-clients/OAuthClientRecord";

export default function OAuthClientDetailPage() {
  const params = useParams<{ id: string }>();
  return (
    <Suspense fallback={<PageBodySkeleton />}>
      <OAuthClientRecord mode="show" clientId={params.id} />
    </Suspense>
  );
}
