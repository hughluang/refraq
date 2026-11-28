"use client";

import { Suspense } from "react";

import { PageBodySkeleton } from "@/components/feedback/PageBodySkeleton";
import { OAuthClientRecord } from "@/features/oauth-clients/OAuthClientRecord";

export default function OAuthClientCreatePage() {
  return (
    <Suspense fallback={<PageBodySkeleton />}>
      <OAuthClientRecord mode="create" />
    </Suspense>
  );
}
