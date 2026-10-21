"use client";

import { Suspense } from "react";

import { PageBodySkeleton } from "@/components/feedback/PageBodySkeleton";
import { EmailAccountRecord } from "@/features/email-accounts/EmailAccountRecord";

export default function EmailAccountCreatePage() {
  return (
    <Suspense fallback={<PageBodySkeleton />}>
      <EmailAccountRecord mode="create" />
    </Suspense>
  );
}
