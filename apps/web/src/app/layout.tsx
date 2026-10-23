import "@fontsource-variable/inter";
import "@fontsource-variable/jetbrains-mono";
import "@xyflow/react/dist/style.css";
import "./globals.css";

import type { Metadata, Viewport } from "next";
import Script from "next/script";
import type { ReactNode } from "react";

import { Providers } from "@/lib/providers";
import { THEME_SCRIPT } from "@/lib/theme-script";

export const metadata: Metadata = {
  title: { default: "Euron WorkflowEngine", template: "%s | WorkflowEngine" },
  description:
    "Self-hosted workflow automation: a visual editor, signed webhooks, schedules and events, and durable executions with retries.",
  icons: { icon: "/icon.svg" },
};

export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#fafbfb" },
    { media: "(prefers-color-scheme: dark)", color: "#0b0f0e" },
  ],
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_SCRIPT }} />
      </head>
      <body>
        <Script src="/env.js" strategy="beforeInteractive" />
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
