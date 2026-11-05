import { PolicySection } from "./PolicySection";
import { AccountSection } from "@/features/account/AccountSection";
import { UsageSection } from "@/features/billing/UsageSection";
import { UpdatesSection } from "./UpdatesSection";

/** Additional settings cards contributed by subsystems. */
export const settingsSections: React.ComponentType[] = [AccountSection, UsageSection, PolicySection, UpdatesSection];
