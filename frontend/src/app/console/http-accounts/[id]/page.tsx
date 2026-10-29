"use client";

import { Suspense } from "react";
import { useParams } from "next/navigation";

import { PageBodySkeleton } from "@/components/feedback/PageBodySkeleton";
import { HttpAccountRecord } from "@/features/http-accounts/HttpAccountRecord";

export default function HttpAccountDetailPage() {
  const params = useParams<{ id: string }>();
  return (
    <Suspense fallback={<PageBodySkeleton />}>
      <HttpAccountRecord mode="show" accountId={params.id} />
    </Suspense>
  );
}
