"use client";

import type { ComponentType } from "react";
import {
  IconAdjustments,
  IconAlertTriangle,
  IconApps,
  IconArrowBackUp,
  IconArrowForwardUp,
  IconArrowsExchange,
  IconArrowsMaximize,
  IconArrowsJoin2,
  IconArrowsSplit2,
  IconBolt,
  IconBook,
  IconBox,
  IconBrain,
  IconCalendarTime,
  IconCategory,
  IconCheck,
  IconChevronDown,
  IconChevronLeft,
  IconChevronRight,
  IconCircleDashed,
  IconCircleFilled,
  IconCircleX,
  IconClock,
  IconCode,
  IconCopyOff,
  IconLoader,
  IconDatabase,
  IconDeviceDesktop,
  IconDotsVertical,
  IconFilter,
  IconForms,
  IconHandFinger,
  IconInbox,
  IconIdBadge,
  IconInfoCircle,
  IconKey,
  IconKeyboard,
  IconLanguage,
  IconLayoutDashboard,
  IconList,
  IconListCheck,
  IconMoon,
  IconPalette,
  IconPencil,
  IconPlayerPlayFilled,
  IconPlug,
  IconPlugConnected,
  IconPlus,
  IconRepeat,
  IconRoute,
  IconSearch,
  IconSend,
  IconSettings,
  IconShieldLock,
  IconStack2,
  IconSun,
  IconTable,
  IconTableImport,
  IconUserCircle,
  IconUsers,
  IconUsersGroup,
  IconVariable,
  IconMail,
  IconMap,
  IconWebhook,
  IconX,
  IconZoomIn,
  IconZoomOut,
  type IconProps,
} from "@tabler/icons-react";

export const ICON_SIZE = 16;
export const ICON_STROKE = 1.5;

type IconComponent = ComponentType<IconProps>;

function withDefaults(Component: IconComponent) {
  function ConsoleIcon({
    size = ICON_SIZE,
    stroke = ICON_STROKE,
    ...props
  }: IconProps) {
    return <Component size={size} stroke={stroke} {...props} />;
  }
  return ConsoleIcon;
}

export const AdjustmentsIcon = withDefaults(IconAdjustments);
export const AlertIcon = withDefaults(IconAlertTriangle);
export const CheckIcon = withDefaults(IconCheck);
export const CircleDashedIcon = withDefaults(IconCircleDashed);
export const ClockIcon = withDefaults(IconClock);
export const ErrorIcon = withDefaults(IconCircleX);
export const LoaderIcon = withDefaults(IconLoader);
export const UndoIcon = withDefaults(IconArrowBackUp);
export const RedoIcon = withDefaults(IconArrowForwardUp);
export const StatusDotIcon = withDefaults(IconCircleFilled);
export const DesktopIcon = withDefaults(IconDeviceDesktop);
export const DotsIcon = withDefaults(IconDotsVertical);
export const EmptyIcon = withDefaults(IconInbox);
export const InfoIcon = withDefaults(IconInfoCircle);
export const LanguageIcon = withDefaults(IconLanguage);
export const ListIcon = withDefaults(IconList);
export const MoonIcon = withDefaults(IconMoon);
export const PencilIcon = withDefaults(IconPencil);
export const PlayIcon = withDefaults(IconPlayerPlayFilled);
export const PlusIcon = withDefaults(IconPlus);
export const VersionsIcon = withDefaults(IconStack2);
export const SunIcon = withDefaults(IconSun);
export const CloseIcon = withDefaults(IconX);
export const SearchIcon = withDefaults(IconSearch);
export const NavCollapseIcon = withDefaults(IconChevronLeft);
export const NavExpandIcon = withDefaults(IconChevronRight);
export const ChevronDownIcon = withDefaults(IconChevronDown);
export const FitViewIcon = withDefaults(IconArrowsMaximize);
export const KeyboardIcon = withDefaults(IconKeyboard);
export const MinimapIcon = withDefaults(IconMap);
export const ZoomInIcon = withDefaults(IconZoomIn);
export const ZoomOutIcon = withDefaults(IconZoomOut);

export const BoltIcon = withDefaults(IconBolt);
export const BoxIcon = withDefaults(IconBox);
export const CalendarTimeIcon = withDefaults(IconCalendarTime);
export const CodeIcon = withDefaults(IconCode);
export const CopyOffIcon = withDefaults(IconCopyOff);
export const DatabaseIcon = withDefaults(IconDatabase);
export const FilterIcon = withDefaults(IconFilter);
export const FormsIcon = withDefaults(IconForms);
export const HandFingerIcon = withDefaults(IconHandFinger);
export const JoinIcon = withDefaults(IconArrowsJoin2);
export const MailIcon = withDefaults(IconMail);
export const PlugConnectedIcon = withDefaults(IconPlugConnected);
export const RepeatIcon = withDefaults(IconRepeat);
export const SendIcon = withDefaults(IconSend);
export const SplitIcon = withDefaults(IconArrowsSplit2);
export const TableImportIcon = withDefaults(IconTableImport);
export const VariableIcon = withDefaults(IconVariable);
export const WebhookIcon = withDefaults(IconWebhook);

/** Kebab-case Tabler names emitted by the Console Module catalog seed. */
const MODULE_ICONS: Record<string, ReturnType<typeof withDefaults>> = {
  "layout-dashboard": withDefaults(IconLayoutDashboard),
  users: withDefaults(IconUsers),
  "users-group": withDefaults(IconUsersGroup),
  "id-badge": withDefaults(IconIdBadge),
  plug: withDefaults(IconPlug),
  "shield-lock": withDefaults(IconShieldLock),
  key: withDefaults(IconKey),
  database: withDefaults(IconDatabase),
  table: withDefaults(IconTable),
  category: withDefaults(IconCategory),
  "arrows-exchange": withDefaults(IconArrowsExchange),
  box: withDefaults(IconBox),
  book: withDefaults(IconBook),
  route: withDefaults(IconRoute),
  variable: withDefaults(IconVariable),
  "list-check": withDefaults(IconListCheck),
  clock: withDefaults(IconClock),
  settings: withDefaults(IconSettings),
  palette: withDefaults(IconPalette),
  webhook: withDefaults(IconWebhook),
  mail: withDefaults(IconMail),
  brain: withDefaults(IconBrain),
  "user-circle": withDefaults(IconUserCircle),
};

const ModuleFallbackIcon = withDefaults(IconApps);

export function moduleIcon(name: string | null | undefined) {
  if (!name) return ModuleFallbackIcon;
  return MODULE_ICONS[name] ?? ModuleFallbackIcon;
}
