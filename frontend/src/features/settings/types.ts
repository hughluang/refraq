export type SettingsSource = "env" | "override";

export type PlatformSettings = {
  refraq_env: string;
  admin_session_ttl_hours: number;
  admin_session_ttl_hours_source: SettingsSource;
  admin_session_ttl_hours_default: number;
};
