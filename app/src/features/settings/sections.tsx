import { AccountSection } from "@/features/account/AccountSection";
import { UsageSection } from "@/features/billing/UsageSection";
import { ReferralsSection } from "@/features/billing/ReferralsSection";
import { UpdatesSection } from "./UpdatesSection";
import { ConnectionSection } from "./ConnectionSection";

/** Additional settings cards contributed by subsystems. */
export const settingsSections: React.ComponentType[] = [ConnectionSection, AccountSection, UsageSection, ReferralsSection, UpdatesSection];
