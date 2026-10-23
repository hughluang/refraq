import {
  AdjustmentsIcon,
  AlertIcon,
  BoltIcon,
  BoxIcon,
  CalendarTimeIcon,
  CodeIcon,
  CopyOffIcon,
  DatabaseIcon,
  DatabaseSearchIcon,
  FilterIcon,
  FormsIcon,
  HandFingerIcon,
  JoinIcon,
  LayoutRowsIcon,
  MailIcon,
  PlugConnectedIcon,
  RepeatIcon,
  SendIcon,
  SplitIcon,
  TableImportIcon,
  TablePlusIcon,
  VariableIcon,
  WebhookIcon,
} from "@/components/icons";

export type FamilyTint = "orange" | "blue" | "gray" | "teal" | "grape";

export type NodeIcon = typeof BoxIcon;

const FAMILY_TINT: Record<string, FamilyTint> = {
  trigger: "orange",
  read: "blue",
  transform: "gray",
  volume: "gray",
  state: "gray",
  write: "teal",
  action: "grape",
};

const TYPE_ICON: Record<string, NodeIcon> = {
  "trigger.manual": HandFingerIcon,
  "trigger.scheduled": CalendarTimeIcon,
  "trigger.error": AlertIcon,
  "read.sql": DatabaseIcon,
  "read.source_query": PlugConnectedIcon,
  "transform.set_fields": FormsIcon,
  "transform.code": CodeIcon,
  "transform.if": SplitIcon,
  "transform.filter": FilterIcon,
  "transform.merge": JoinIcon,
  "transform.deduplicate": CopyOffIcon,
  "volume.for": RepeatIcon,
  "volume.dataset_query": DatabaseSearchIcon,
  "volume.materialize": TablePlusIcon,
  "volume.batch_read": LayoutRowsIcon,
  "state.variable": VariableIcon,
  "write.entity": TableImportIcon,
  "action.webhook": WebhookIcon,
  "action.email": MailIcon,
};

const FAMILY_ICON: Record<string, NodeIcon> = {
  trigger: BoltIcon,
  read: DatabaseIcon,
  transform: AdjustmentsIcon,
  volume: RepeatIcon,
  state: VariableIcon,
  write: TableImportIcon,
  action: SendIcon,
};

export function familyTint(family: string): FamilyTint {
  return Object.hasOwn(FAMILY_TINT, family) ? FAMILY_TINT[family]! : "gray";
}

export function nodeTypeIcon(type: string, family: string): NodeIcon {
  if (Object.hasOwn(TYPE_ICON, type)) return TYPE_ICON[type]!;
  return Object.hasOwn(FAMILY_ICON, family) ? FAMILY_ICON[family]! : BoxIcon;
}
