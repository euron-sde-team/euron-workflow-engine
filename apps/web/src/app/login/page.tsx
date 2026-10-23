"use client";

import { RefreshCcw, ShieldCheck, Workflow } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState, type FormEvent } from "react";

import { Wordmark } from "@/components/brand";
import { Button } from "@/components/ui/button";
import { ErrorNotice, Spinner } from "@/components/ui/feedback";
import { Input, Label } from "@/components/ui/input";
import { ApiError } from "@/lib/api";
import { runtimeEnv } from "@/lib/runtime-env";
import { useLogin, useSignup, useSystemInfo } from "@/lib/queries";

const FEATURES = [
  {
    icon: Workflow,
    title: "Build on a canvas",
    text: "Nodes for HTTP, email, S3, SQS, Postgres and Slack. No code to deploy.",
  },
  {
    icon: RefreshCcw,
    title: "Runs that finish",
    text: "Retries with backoff, timeouts, resume from the failed step.",
  },
  {
    icon: ShieldCheck,
    title: "Secrets stay secret",
    text: "Credentials are KMS-encrypted and never shown again.",
  },
];

function LoginForm() {
  const router = useRouter();
  const params = useSearchParams();
  const system = useSystemInfo();
  const login = useLogin();
  const signup = useSignup();
  const [mode, setMode] = useState<"signin" | "signup">("signin");
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const setup = system.data?.needs_setup ?? false;
  const creating = setup || mode === "signup";
  const pending = login.isPending || signup.isPending;
  const error = (creating ? signup.error : login.error) as ApiError | null;

  async function submit(event: FormEvent) {
    event.preventDefault();
    try {
      if (creating) await signup.mutateAsync({ email, name, password });
      else await login.mutateAsync({ email, password });
      const next = params.get("next");
      router.replace(next && next.startsWith("/") && !next.startsWith("//") ? next : "/");
    } catch {
      // The error is rendered from the mutation state.
    }
  }

  return (
    <form onSubmit={submit} className="w-full max-w-sm space-y-4" noValidate>
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">
          {setup ? "Set up WorkflowEngine" : creating ? "Create your account" : "Welcome back"}
        </h1>
        <p className="text-muted-foreground mt-1.5 text-[13.5px]">
          {setup
            ? "Create the first account. It becomes the administrator of this deployment."
            : creating
              ? "You will get a private workspace for your automations."
              : "Sign in to build and run your workflows."}
        </p>
      </div>
      {creating ? (
        <div className="space-y-1.5">
          <Label htmlFor="name">Name</Label>
          <Input
            id="name"
            autoComplete="name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            required
          />
        </div>
      ) : null}
      <div className="space-y-1.5">
        <Label htmlFor="email">Email</Label>
        <Input
          id="email"
          type="email"
          autoComplete="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          required
          autoFocus
        />
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="password">Password</Label>
        <Input
          id="password"
          type="password"
          autoComplete={creating ? "new-password" : "current-password"}
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          required
        />
      </div>
      {error ? <ErrorNotice message={error.message} /> : null}
      <Button type="submit" size="lg" className="w-full" disabled={pending}>
        {pending ? <Spinner className="text-primary-foreground" /> : null}
        {creating ? "Create account" : "Sign in"}
      </Button>
      {!setup && system.data?.allow_signup ? (
        <p className="text-muted-foreground text-center text-[13px]">
          {creating ? "Already have an account?" : "New here?"}{" "}
          <button
            type="button"
            className="text-primary font-medium hover:underline"
            onClick={() => setMode(creating ? "signin" : "signup")}
          >
            {creating ? "Sign in" : "Create an account"}
          </button>
        </p>
      ) : null}
    </form>
  );
}

export default function LoginPage() {
  const productName = runtimeEnv().productName;
  return (
    <main className="grid min-h-dvh lg:grid-cols-[minmax(0,1.05fr)_minmax(0,1fr)]">
      <section className="relative hidden overflow-hidden bg-[#071a18] p-12 text-white lg:flex lg:flex-col lg:justify-between">
        <div
          aria-hidden
          className="pointer-events-none absolute inset-0 opacity-90"
          style={{
            background:
              "radial-gradient(60% 50% at 20% 10%, rgb(15 118 110 / 0.6), transparent 70%), radial-gradient(50% 40% at 90% 90%, rgb(45 212 191 / 0.25), transparent 70%)",
          }}
        />
        <Wordmark name={productName} className="relative [&_span]:text-white" />
        <div className="relative max-w-md">
          <h2 className="text-[34px] leading-tight font-semibold tracking-tight">
            Automations you can trust to finish.
          </h2>
          <p className="mt-3 text-[15px] text-white/70">
            Webhooks, schedules and events start durable workflows on infrastructure you own.
          </p>
          <ul className="mt-8 space-y-4">
            {FEATURES.map(({ icon: Icon, title, text }) => (
              <li key={title} className="flex gap-3">
                <span className="mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-lg bg-white/10">
                  <Icon className="size-4" />
                </span>
                <span>
                  <span className="block text-sm font-medium">{title}</span>
                  <span className="block text-[13px] text-white/65">{text}</span>
                </span>
              </li>
            ))}
          </ul>
        </div>
        <p className="relative text-xs text-white/45">Open source under the MIT License.</p>
      </section>
      <section className="flex items-center justify-center p-6 sm:p-12">
        <div className="w-full max-w-sm">
          <Wordmark name={productName} className="mb-10 lg:hidden" />
          <Suspense fallback={<Spinner />}>
            <LoginForm />
          </Suspense>
        </div>
      </section>
    </main>
  );
}
