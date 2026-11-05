import { PolicySection } from "./PolicySection";
import { AccountSection } from "@/features/account/AccountSection";
import { UpdatesSection } from "./UpdatesSection";

/** Additional settings cards contributed by subsystems. */
export const settingsSections: React.ComponentType[] = [AccountSection, PolicySection, UpdatesSection];
