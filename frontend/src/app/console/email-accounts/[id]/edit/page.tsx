"use client";

import { Suspense } from "react";
import { useParams } from "next/navigation";

import { PageBodySkeleton } from "@/components/feedback/PageBodySkeleton";
import { EmailAccountRecord } from "@/features/email-accounts/EmailAccountRecord";

export default function EmailAccountEditPage() {
  const params = useParams<{ id: string }>();
  return (
    <Suspense fallback={<PageBodySkeleton />}>
      <EmailAccountRecord mode="edit" accountId={params.id} />
    </Suspense>
  );
}
