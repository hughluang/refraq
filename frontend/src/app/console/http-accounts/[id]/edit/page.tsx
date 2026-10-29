"use client";

import { Suspense } from "react";
import { useParams } from "next/navigation";

import { PageBodySkeleton } from "@/components/feedback/PageBodySkeleton";
import { HttpAccountRecord } from "@/features/http-accounts/HttpAccountRecord";

export default function HttpAccountEditPage() {
  const params = useParams<{ id: string }>();
  return (
    <Suspense fallback={<PageBodySkeleton />}>
      <HttpAccountRecord mode="edit" accountId={params.id} />
    </Suspense>
  );
}
