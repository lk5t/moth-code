import { AccountSection } from "@/features/account/AccountSection";
import { UsageSection } from "@/features/billing/UsageSection";
import { ReferralsSection } from "@/features/billing/ReferralsSection";
import { UpdatesSection } from "./UpdatesSection";
import { ConnectionSection } from "./ConnectionSection";
import { IntelligenceSection } from "@/features/intelligence/IntelligenceSection";

/** Additional settings cards contributed by subsystems. */
export const settingsSections: React.ComponentType[] = [ConnectionSection, AccountSection, IntelligenceSection, UsageSection, ReferralsSection, UpdatesSection];
