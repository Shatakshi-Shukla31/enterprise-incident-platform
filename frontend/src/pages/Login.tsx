import { useState, type FormEvent } from "react";
import { useAuth } from "../auth/AuthContext";
import { ThemeToggle } from "../components/ThemeToggle";
import { Button, ErrorNote, Field, inputClass } from "../components/ui";

type Audience = "user" | "admin";
type Mode = "signin" | "create";

const EMPTY = { name: "", email: "", password: "", confirm: "", code: "" };

const ICONS = {
  person: "M20 21a8 8 0 0 0-16 0M12 13a5 5 0 1 0 0-10 5 5 0 0 0 0 10z",
  shield: "M12 3l8 3v6c0 5-3.4 8.4-8 9-4.6-.6-8-4-8-9V6z",
  eye: "M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7-10-7-10-7zM12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6z",
  eyeOff: "M3 3l18 18M10.6 5.1A10.7 10.7 0 0 1 12 5c6.4 0 10 7 10 7a17 17 0 0 1-3.2 4.1M6.6 6.6A16.9 16.9 0 0 0 2 12s3.6 7 10 7a10.6 10.6 0 0 0 4.4-.9M9.9 9.9a3 3 0 0 0 4.2 4.2",
};

const AUDIENCES: { value: Audience; label: string; detail: string; icon: string }[] = [
  { value: "user", label: "User", detail: "Report problems and track your tickets", icon: ICONS.person },
  { value: "admin", label: "Admin", detail: "Support staff, managers and admins", icon: ICONS.shield },
];

const MODES: { value: Mode; label: string }[] = [
  { value: "signin", label: "Sign in" },
  { value: "create", label: "Create account" },
];

const HEADINGS: Record<Audience, Record<Mode, { title: string; detail: string }>> = {
  user: {
    signin: { title: "Welcome back", detail: "Sign in to see your tickets and alerts." },
    create: { title: "Create your account", detail: "You can raise your first ticket straight away." },
  },
  admin: {
    signin: { title: "Staff sign in", detail: "Open the queue, dashboard and approvals." },
    create: { title: "Create an admin account", detail: "You need this system's admin access code." },
  },
};

const JOURNEY = [
  ["Report", "Describe the problem in your own words."],
  ["Route", "AI suggests the category and the right team."],
  ["Track", "Deadlines and alerts keep every ticket moving."],
  ["Resolve", "Fixes come with sources you can check."],
];

function Icon({ path }: { path: string }) {
  return (
    <svg aria-hidden width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d={path} />
    </svg>
  );
}

function PasswordField({
  label,
  hint,
  value,
  autoComplete,
  minLength,
  onChange,
}: {
  label: string;
  hint?: string;
  value: string;
  autoComplete: string;
  minLength?: number;
  onChange: (value: string) => void;
}) {
  const [shown, setShown] = useState(false);
  return (
    <div className="relative">
      <Field label={label} hint={hint}>
        <input className={`${inputClass} pr-10`} type={shown ? "text" : "password"} autoComplete={autoComplete} minLength={minLength} required value={value} onChange={(e) => onChange(e.target.value)} />
      </Field>
      <button
        type="button"
        aria-label={`${shown ? "Hide" : "Show"} ${label.toLowerCase()}`}
        className="absolute top-7 right-1.5 rounded p-1.5 text-ink-3 hover:text-ink"
        onClick={() => setShown(!shown)}
      >
        <Icon path={shown ? ICONS.eyeOff : ICONS.eye} />
      </button>
    </div>
  );
}

function Story() {
  return (
    <section className="login-hero flex flex-col justify-between gap-8 p-6 text-white md:p-10 lg:p-14">
      <p className="flex items-center gap-2.5 font-semibold">
        <img src="/favicon.svg" alt="" width="28" height="28" className="rounded-md" />
        Incident Platform
      </p>
      <div className="max-w-md">
        <h1 className="text-3xl leading-tight font-semibold md:text-4xl">From first report to fixed.</h1>
        <p className="mt-3 text-white/80">One place to raise incidents, watch deadlines and find answers you can trust.</p>
      </div>
      <ol className="hidden max-w-md lg:block">
        {JOURNEY.map(([step, detail], index) => (
          <li key={step} className="relative flex gap-4 pb-6 last:pb-0">
            {index < JOURNEY.length - 1 && <span aria-hidden className="absolute top-8 bottom-0 left-3.5 w-px bg-white/25" />}
            <span aria-hidden className="tabular flex size-7 shrink-0 items-center justify-center rounded-full bg-white/15 text-sm font-semibold">
              {index + 1}
            </span>
            <span>
              <span className="block font-medium">{step}</span>
              <span className="block text-sm text-white/75">{detail}</span>
            </span>
          </li>
        ))}
      </ol>
    </section>
  );
}

export function LoginPage() {
  const { signIn, register, exploreDemo } = useAuth();
  const [audience, setAudience] = useState<Audience>("user");
  const [mode, setMode] = useState<Mode>("signin");
  const [form, setForm] = useState(EMPTY);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  const creating = mode === "create";
  const admin = audience === "admin";
  const heading = HEADINGS[audience][mode];
  const update = (field: keyof typeof EMPTY) => (value: string) => setForm((current) => ({ ...current, [field]: value }));

  function choose(next: { audience?: Audience; mode?: Mode }) {
    if (next.audience) setAudience(next.audience);
    if (next.mode) setMode(next.mode);
    setError(null);
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (creating && form.password !== form.confirm) {
      setError(new Error("The two passwords do not match."));
      return;
    }
    setBusy(true);
    setError(null);
    try {
      if (creating) {
        await register({ email: form.email, full_name: form.name, password: form.password, ...(admin ? { admin_code: form.code } : {}) });
      } else {
        await signIn(form.email, form.password, { staffOnly: admin });
      }
    } catch (caught) {
      setError(caught);
    } finally {
      setBusy(false);
    }
  }

  async function explore() {
    setBusy(true);
    setError(null);
    try {
      await exploreDemo();
    } catch (caught) {
      setError(caught);
    } finally {
      setBusy(false);
    }
  }

  const idleLabel = creating ? "Create account" : "Sign in";
  const busyLabel = creating ? "Creating account…" : "Signing in…";

  return (
    <div className="min-h-screen lg:grid lg:grid-cols-[minmax(0,1.1fr)_minmax(0,1fr)]">
      <Story />
      <main className="relative flex items-center justify-center p-4 md:p-8">
        <div className="absolute top-4 right-4">
          <ThemeToggle />
        </div>
        <form onSubmit={submit} className="mt-12 w-full max-w-md space-y-4 lg:mt-0">
          <fieldset className="grid grid-cols-2 gap-2">
            <legend className="sr-only">Account type</legend>
            {AUDIENCES.map((option) => (
              <label key={option.value} className="cursor-pointer">
                <input type="radio" name="audience" className="peer sr-only" checked={audience === option.value} onChange={() => choose({ audience: option.value })} />
                <span className="flex h-full flex-col gap-1 rounded-lg border border-line bg-surface p-3 transition-colors peer-checked:border-accent peer-checked:bg-accent-soft peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2 peer-focus-visible:outline-accent hover:bg-sunken">
                  <span className="flex items-center gap-2 text-sm font-semibold text-ink">
                    <Icon path={option.icon} />
                    {option.label}
                  </span>
                  <span className="text-xs text-ink-2">{option.detail}</span>
                </span>
              </label>
            ))}
          </fieldset>

          <div>
            <h2 className="text-xl font-semibold text-ink">{heading.title}</h2>
            <p className="text-sm text-ink-2">{heading.detail}</p>
          </div>

          <fieldset className="grid grid-cols-2 gap-1 rounded-lg bg-sunken p-1">
            <legend className="sr-only">Sign in or create an account</legend>
            {MODES.map((option) => (
              <label key={option.value} className="cursor-pointer">
                <input type="radio" name="mode" className="peer sr-only" checked={mode === option.value} onChange={() => choose({ mode: option.value })} />
                <span className="block rounded-md px-3 py-1.5 text-center text-sm font-medium text-ink-2 transition-colors peer-checked:bg-surface peer-checked:text-ink peer-checked:shadow-sm peer-focus-visible:outline-2 peer-focus-visible:outline-accent">
                  {option.label}
                </span>
              </label>
            ))}
          </fieldset>

          {creating && (
            <Field label="Full name">
              <input className={inputClass} autoComplete="name" required minLength={2} maxLength={120} value={form.name} onChange={(e) => update("name")(e.target.value)} />
            </Field>
          )}
          <Field label="Email">
            <input className={inputClass} type="email" autoComplete={creating ? "email" : "username"} required value={form.email} onChange={(e) => update("email")(e.target.value)} />
          </Field>
          <PasswordField
            label="Password"
            hint={creating ? "At least 12 characters." : undefined}
            minLength={creating ? 12 : undefined}
            autoComplete={creating ? "new-password" : "current-password"}
            value={form.password}
            onChange={update("password")}
          />
          {creating && <PasswordField label="Confirm password" autoComplete="new-password" value={form.confirm} onChange={update("confirm")} />}
          {creating && admin && <PasswordField label="Admin access code" hint="Set by whoever runs this system." autoComplete="off" value={form.code} onChange={update("code")} />}

          <ErrorNote error={error} />
          <Button type="submit" className="w-full" disabled={busy}>
            {busy ? busyLabel : idleLabel}
          </Button>
          <div aria-hidden className="flex items-center gap-3 text-xs text-ink-3">
            <span className="h-px flex-1 bg-line" />
            or
            <span className="h-px flex-1 bg-line" />
          </div>
          <Button variant="secondary" className="w-full" disabled={busy} onClick={() => void explore()}>
            Explore the demo
          </Button>
          <p className="text-center text-xs text-ink-3">
            No account needed. You look around as a manager, and nothing can be changed. All data is made up, so please
            use a password you don't use anywhere else.
          </p>
        </form>
      </main>
    </div>
  );
}
