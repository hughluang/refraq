"use client";

import { useParams } from "next/navigation";

import { UserShow } from "@/features/users/UserShow";

export default function UserShowPage() {
  const params = useParams<{ id: string }>();
  return <UserShow userId={params.id} />;
}
