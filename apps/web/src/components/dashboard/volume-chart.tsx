"use client";

import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { formatNumber } from "@/lib/format";
import type { Dashboard } from "@/lib/types";

const axis = { fontSize: 11, fill: "var(--subtle)" };

type TooltipEntry = { name?: string; value?: number; color?: string };

function ChartTooltip({ active, payload, label }: { active?: boolean; payload?: TooltipEntry[]; label?: string }) {
  if (!active || !payload?.length) return null;
  const total = payload.reduce((sum, entry) => sum + (entry.value ?? 0), 0);
  return (
    <div className="rounded-lg border border-border bg-card px-3 py-2 text-xs shadow-md">
      <p className="mb-1 font-medium">
        {label} <span className="font-normal text-muted-foreground">({formatNumber(total)} runs)</span>
      </p>
      {payload.map((entry) => (
        <p key={entry.name} className="flex items-center gap-2 text-muted-foreground">
          <span className="size-2 rounded-full" style={{ background: entry.color }} />
          {entry.name}: <span className="font-medium text-foreground">{formatNumber(entry.value ?? 0)}</span>
        </p>
      ))}
    </div>
  );
}

export function VolumeChart({ volume }: { volume: Dashboard["volume"] }) {
  return (
    <ResponsiveContainer width="100%" height={250}>
      <BarChart data={volume} margin={{ top: 8, right: 8, left: -20, bottom: 0 }}>
        <CartesianGrid vertical={false} stroke="var(--border)" />
        <XAxis dataKey="label" tick={axis} tickLine={false} axisLine={false} minTickGap={16} />
        <YAxis allowDecimals={false} tick={axis} tickLine={false} axisLine={false} width={40} />
        <Tooltip content={<ChartTooltip />} cursor={{ fill: "var(--muted)" }} />
        <Bar dataKey="succeeded" name="Succeeded" stackId="v" fill="var(--chart-success)" />
        <Bar dataKey="failed" name="Failed" stackId="v" fill="var(--chart-failed)" />
        <Bar dataKey="cancelled" name="Cancelled" stackId="v" fill="var(--chart-cancelled)" />
        <Bar dataKey="in_progress" name="In progress" stackId="v" fill="var(--chart-progress)" radius={[4, 4, 0, 0]} />
      </BarChart>
    </ResponsiveContainer>
  );
}
