"use client";

import { Search } from "lucide-react";
import { useMemo, useState, type DragEvent } from "react";

import { NodeIcon } from "@/components/node-icon";
import { Input } from "@/components/ui/input";
import type { NodeType } from "@/lib/types";

const GROUPS: { key: NodeType["category"]; label: string }[] = [
  { key: "trigger", label: "Triggers" },
  { key: "core", label: "Data" },
  { key: "flow", label: "Flow" },
  { key: "integration", label: "Integrations" },
];

export const DRAG_TYPE = "application/x-wfe-node-type";

export function Palette({
  types,
  onAdd,
  disabled,
}: {
  types: NodeType[];
  onAdd: (type: NodeType) => void;
  disabled?: boolean;
}) {
  const [query, setQuery] = useState("");
  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return q
      ? types.filter((t) => `${t.name} ${t.description} ${t.type}`.toLowerCase().includes(q))
      : types;
  }, [types, query]);

  function onDragStart(event: DragEvent, type: NodeType) {
    event.dataTransfer.setData(DRAG_TYPE, type.type);
    event.dataTransfer.effectAllowed = "move";
  }

  return (
    <div className="flex h-full flex-col">
      <div className="relative p-3">
        <Search
          className="text-subtle pointer-events-none absolute top-1/2 left-5 size-4 -translate-y-1/2"
          aria-hidden
        />
        <Input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search nodes"
          className="pl-8"
          aria-label="Search nodes"
        />
      </div>
      <div className="scroll-quiet min-h-0 flex-1 overflow-y-auto px-3 pb-4">
        {GROUPS.map((group) => {
          const items = filtered.filter((t) => t.category === group.key);
          if (!items.length) return null;
          return (
            <section key={group.key} className="mb-3">
              <h3 className="text-subtle px-1 pb-1.5 text-[11px] font-medium tracking-wider uppercase">
                {group.label}
              </h3>
              <ul className="space-y-1">
                {items.map((type) => (
                  <li key={type.type}>
                    <button
                      type="button"
                      draggable={!disabled}
                      disabled={disabled}
                      onDragStart={(event) => onDragStart(event, type)}
                      onClick={() => onAdd(type)}
                      className="hover:border-border hover:bg-card flex w-full items-center gap-2.5 rounded-lg border border-transparent px-2 py-1.5 text-left transition-colors disabled:opacity-50"
                      title={type.description}
                      data-testid={`palette-${type.type}`}
                    >
                      <NodeIcon icon={type.icon} category={type.category} className="size-7" />
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-[13px] font-medium">{type.name}</span>
                        <span className="text-muted-foreground block truncate text-[11.5px]">
                          {type.description}
                        </span>
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            </section>
          );
        })}
        {filtered.length === 0 ? (
          <p className="text-muted-foreground px-1 text-[13px]">No node matches.</p>
        ) : null}
      </div>
    </div>
  );
}
