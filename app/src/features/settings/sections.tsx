import { AccountSection } from "@/features/account/AccountSection";
import { UsageSection } from "@/features/billing/UsageSection";
import { ReferralsSection } from "@/features/billing/ReferralsSection";
import { UpdatesSection } from "./UpdatesSection";
import { AdvancedSection } from "./AdvancedSection";

/** Additional settings cards contributed by subsystems. */
export const settingsSections: React.ComponentType[] = [AccountSection, UsageSection, ReferralsSection, UpdatesSection, AdvancedSection];
