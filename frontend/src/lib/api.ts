const baseUrl =
  process.env.NEXT_PUBLIC_REFRAQ_API_BASE_URL || "http://127.0.0.1:6068";

export async function apiClient(path: string, init?: RequestInit) {
  const response = await fetch(`${baseUrl}${path}`, {
    credentials: "include",
    ...init,
  });

  if (!response.ok) {
    throw new Error(`Request failed: ${response.status}`);
  }

  return response.json();
}
