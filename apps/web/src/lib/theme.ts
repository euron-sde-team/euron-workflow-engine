"use client";

import { useCallback, useSyncExternalStore } from "react";

import { STORAGE_KEY } from "@/lib/theme-script";

export type Theme = "light" | "dark";

function subscribe(callback: () => void): () => void {
  const observer = new MutationObserver(callback);
  observer.observe(document.documentElement, { attributes: true, attributeFilter: ["class"] });
  return () => observer.disconnect();
}

function current(): Theme {
  return document.documentElement.classList.contains("dark") ? "dark" : "light";
}

export function useTheme(): [Theme, () => void] {
  const theme = useSyncExternalStore(subscribe, current, () => "light" as Theme);
  const toggle = useCallback(() => {
    const next: Theme = current() === "dark" ? "light" : "dark";
    document.documentElement.classList.toggle("dark", next === "dark");
    try {
      localStorage.setItem(STORAGE_KEY, next);
    } catch {
      // Private mode or blocked storage: the toggle still works for this page view.
    }
  }, []);
  return [theme, toggle];
}
