export const SOURCE_READ = "sources:read";
export const SOURCE_ACCESS_MANAGE = "sources:access_manage";

export const SOURCE_ACCESS_LEVELS = ["viewer", "steward", "maintainer"] as const;
export type SourceAccessLevel = (typeof SOURCE_ACCESS_LEVELS)[number];

export const MEMBERSHIP_SUBJECT_KINDS = ["user", "group", "role"] as const;
export type MembershipSubjectKind = (typeof MEMBERSHIP_SUBJECT_KINDS)[number];

export type MembershipSubject = {
  type: string;
  id: string;
  display_name: string | null;
  missing: boolean;
};

export type SourceMembership = {
  id: string;
  subject: MembershipSubject;
  target: string;
  level: string;
  created_at: string;
  updated_at: string;
};

export type MembershipWrite = {
  subject: { type: string; id: string };
  level: string;
};

export type SourceAccessContribution = {
  kind: string;
  subject_name: string;
};

export type UserSourceAccessItem = {
  source_id: string;
  key: string;
  name: string;
  level: string;
  contributions: SourceAccessContribution[];
};

type Translate = (key: string) => string;

function catalogLabel(t: Translate, key: string, fallback: string): string {
  const label = t(key);
  return label === key ? fallback : label;
}

export function membershipLevelLabel(t: Translate, level: string): string {
  return catalogLabel(t, `sources.membership.level.${level}`, level);
}

export function membershipKindLabel(t: Translate, kind: string): string {
  return catalogLabel(t, `sources.membership.subjectKind.${kind}`, kind);
}

export function membershipPathLabel(t: Translate, kind: string): string {
  return catalogLabel(t, `sources.membership.path.${kind}`, kind);
}

export function membershipSubjectLabel(t: Translate, subject: MembershipSubject): string {
  if (subject.missing || subject.display_name == null || subject.display_name.trim() === "") {
    return t("sources.membership.subjectMissing");
  }
  return subject.display_name;
}

export function contributionPath(t: Translate, contributions: readonly SourceAccessContribution[]): string {
  return contributions
    .map((item) => {
      const kind = membershipPathLabel(t, item.kind);
      const name = item.subject_name.trim();
      if (name === "" || name === kind) return kind;
      return `${kind} · ${name}`;
    })
    .join("; ");
}

export function isMembershipSubjectKind(value: string): value is MembershipSubjectKind {
  return (MEMBERSHIP_SUBJECT_KINDS as readonly string[]).includes(value);
}
