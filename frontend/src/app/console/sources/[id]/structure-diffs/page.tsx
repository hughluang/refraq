import { redirect } from "next/navigation";

import { sourceDiffsPath } from "@/features/sources/sourceRecordTab";

export default async function SourceStructureDiffsPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  redirect(sourceDiffsPath(id));
}
