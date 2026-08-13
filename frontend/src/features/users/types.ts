export type UserStatus = "active" | "disabled";

export type UserRow = {
  id: string;
  account: string;
  display_name: string;
  email: string | null;
  locale: string;
  display_timezone: string | null;
  role_id: string | null;
  role_key: string | null;
  role_name: string | null;
  status: UserStatus;
  identity_source: "local";
  last_login_at: string | null;
};

export type UserCreateValues = {
  account: string;
  display_name: string;
  password: string;
  role_id: string | null;
};
