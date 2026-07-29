import enUS from "@/locales/en-US/common.json";
import zhCN from "@/locales/zh-CN/common.json";

export const messages = {
  "en-US": enUS,
  "zh-CN": zhCN,
};

export function getDefaultLocale(): "zh-CN" | "en-US" {
  return "en-US";
}
