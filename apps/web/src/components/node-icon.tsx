import {
  Blocks,
  CalendarClock,
  Database,
  Download,
  GitBranch,
  Globe,
  Hourglass,
  ListStart,
  Mail,
  Merge,
  MessageSquare,
  OctagonX,
  Play,
  RadioTower,
  Repeat,
  Send,
  Shuffle,
  Split,
  Timer,
  Upload,
  Variable,
  Webhook,
  type LucideIcon,
} from "lucide-react";

import { cn } from "@/lib/cn";

const ICONS: Record<string, LucideIcon> = {
  play: Play,
  webhook: Webhook,
  "calendar-clock": CalendarClock,
  timer: Timer,
  "radio-tower": RadioTower,
  shuffle: Shuffle,
  variable: Variable,
  send: Send,
  "git-branch": GitBranch,
  split: Split,
  merge: Merge,
  repeat: Repeat,
  hourglass: Hourglass,
  "octagon-x": OctagonX,
  globe: Globe,
  mail: Mail,
  "message-square": MessageSquare,
  upload: Upload,
  download: Download,
  "list-start": ListStart,
  database: Database,
};

/** The category colours the node chip; the icon names come from the API's node catalog. */
const CATEGORY: Record<string, string> = {
  trigger: "bg-warning-soft text-warning",
  core: "bg-accent text-accent-foreground",
  flow: "bg-info-soft text-info",
  integration: "bg-success-soft text-success",
};

export function NodeIcon({
  icon,
  category,
  className,
}: {
  icon: string;
  category?: string;
  className?: string;
}) {
  const Icon = ICONS[icon] ?? Blocks;
  return (
    <span
      className={cn(
        "flex size-8 shrink-0 items-center justify-center rounded-lg [&_svg]:size-4",
        CATEGORY[category ?? "core"] ?? CATEGORY.core,
        className,
      )}
      aria-hidden
    >
      <Icon />
    </span>
  );
}
