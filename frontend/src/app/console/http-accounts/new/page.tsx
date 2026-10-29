"use client";

import { Suspense } from "react";

import { PageBodySkeleton } from "@/components/feedback/PageBodySkeleton";
import { HttpAccountRecord } from "@/features/http-accounts/HttpAccountRecord";

export default function HttpAccountCreatePage() {
  return (
    <Suspense fallback={<PageBodySkeleton />}>
      <HttpAccountRecord mode="create" />
    </Suspense>
  );
}
