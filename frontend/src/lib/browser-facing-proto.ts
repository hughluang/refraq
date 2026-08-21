/**
 * Protocol the Management Console presents to browsers.
 *
 * Self-deploy web listens on HTTP by default. Client `X-Forwarded-Proto` is
 * not authoritative (spoofable on the published web port). Operators who
 * terminate TLS in front of web set `REFRAQ_BROWSER_FACING_PROTO=https` so
 * the `/api` rewrite can stamp a trusted value for Session `Secure`.
 */
export function browserFacingProtoFromEnv(
  env: Record<string, string | undefined> = process.env,
): "http" | "https" {
  const configured = env.REFRAQ_BROWSER_FACING_PROTO?.trim().toLowerCase();
  if (configured === "https" || configured === "http") {
    return configured;
  }
  return "http";
}
