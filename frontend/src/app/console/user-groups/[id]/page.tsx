"use client";

import { useParams } from "next/navigation";

import { UserGroupShow } from "@/features/subjects/UserGroupShow";

export default function UserGroupPage() {
  const params = useParams<{ id: string }>();
  return <UserGroupShow groupId={params.id} />;
}
