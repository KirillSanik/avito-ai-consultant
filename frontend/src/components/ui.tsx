"use client";

import type { ReactNode } from "react";

import type { Role } from "@/lib/types";


export function Logo({ compact = false }: { compact?: boolean }) {
  return (
    <div className="flex items-center gap-3">
      <div className={`${compact ? "h-8 w-8 rounded-lg" : "h-12 w-12 rounded-xl"} grid place-items-center bg-primary`}>
        <svg width={compact ? 17 : 24} height={compact ? 17 : 24} fill="none" viewBox="0 0 24 24" aria-hidden>
          <path
            d="M12 2 2 7l10 5 10-5-10-5ZM2 17l10 5 10-5M2 12l10 5 10-5"
            stroke="white"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      </div>
      <span className={`${compact ? "text-base" : "text-2xl"} font-display text-foreground`}>ReviewDesk</span>
    </div>
  );
}


export function RoleToggle({ role, onChange }: { role: Role; onChange: (role: Role) => void }) {
  return (
    <div className="flex rounded-lg border border-border bg-secondary p-0.5">
      {(["reviewer", "methodist"] as Role[]).map((item) => (
        <button
          key={item}
          type="button"
          onClick={() => onChange(item)}
          className={`rounded-md px-3 py-1.5 text-xs font-medium transition ${
            role === item ? "bg-primary text-white" : "text-muted hover:text-foreground"
          }`}
        >
          {item === "reviewer" ? "Ревьюер" : "Методист"}
        </button>
      ))}
    </div>
  );
}


export function AppHeader({
  role,
  accountRole,
  onRoleChange,
  onLogout,
}: {
  role: Role;
  accountRole: Role;
  onRoleChange: (role: Role) => void;
  onLogout: () => void;
}) {
  return (
    <header className="sticky top-0 z-30 border-b border-border bg-white/95 px-5 py-3 backdrop-blur">
      <div className="mx-auto flex max-w-6xl items-center justify-between gap-4">
        <Logo compact />
        <div className="flex items-center gap-2 sm:gap-4">
          {accountRole === "methodist" ? (
            <RoleToggle role={role} onChange={onRoleChange} />
          ) : (
            <span className="rounded-md border border-border bg-secondary px-3 py-1.5 text-xs font-medium text-muted">
              Ревьюер
            </span>
          )}
          <button className="text-xs text-muted transition hover:text-danger" onClick={onLogout}>
            Выйти
          </button>
        </div>
      </div>
    </header>
  );
}


export function ProgressBar({
  value,
  total,
  tone = "accent",
}: {
  value: number;
  total: number;
  tone?: "accent" | "success" | "warning" | "danger";
}) {
  const percent = total > 0 ? Math.min(100, Math.round((value / total) * 100)) : 0;
  const colors = {
    accent: "bg-accent",
    success: "bg-success",
    warning: "bg-warning",
    danger: "bg-danger",
  };
  return (
    <div className="flex items-center gap-3">
      <div className="h-2 flex-1 overflow-hidden rounded-full bg-background">
        <div className={`h-full rounded-full transition-all ${colors[tone]}`} style={{ width: `${percent}%` }} />
      </div>
      <span className="w-9 text-right font-mono text-xs text-muted">{percent}%</span>
    </div>
  );
}


export function ExternalLink({ href, children }: { href: string; children: ReactNode }) {
  return (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      className="inline-flex items-center gap-1.5 rounded-lg border border-indigo-200 bg-indigo-50 px-3 py-1.5 text-xs font-medium text-accent transition hover:bg-indigo-100"
    >
      {children}
      <span aria-hidden>↗</span>
    </a>
  );
}


export function ResourceLinks({
  taskUrl,
  criteriaUrl,
}: {
  taskUrl: string;
  criteriaUrl?: string | null;
}) {
  const criteria = criteriaUrl?.trim();
  return (
    <div className="flex flex-wrap gap-3">
      <ExternalLink href={taskUrl}>Условия задания</ExternalLink>
      {criteria ? <ExternalLink href={criteria}>Критерии (подробно)</ExternalLink> : null}
    </div>
  );
}


export function Modal({
  title,
  onClose,
  children,
}: {
  title: string;
  onClose: () => void;
  children: ReactNode;
}) {
  return (
    <div
      className="fixed inset-0 z-50 grid place-items-center bg-slate-950/50 p-3"
      role="dialog"
      aria-modal="true"
      aria-label={title}
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div className="max-h-[94vh] w-full max-w-4xl overflow-auto rounded-xl bg-white shadow-2xl">
        <div className="sticky top-0 z-10 flex items-center justify-between border-b border-border bg-white px-5 py-3">
          <h2 className="text-sm font-semibold">{title}</h2>
          <button
            type="button"
            className="text-2xl leading-none text-muted hover:text-danger"
            onClick={onClose}
            aria-label="Закрыть"
          >
            ×
          </button>
        </div>
        <div className="p-4">{children}</div>
      </div>
    </div>
  );
}


export function PageLoader({ label = "Загружаем данные…" }: { label?: string }) {
  return (
    <div className="grid min-h-[360px] place-items-center">
      <div className="text-center">
        <div className="mx-auto h-7 w-7 animate-spin rounded-full border-2 border-border border-t-accent" />
        <p className="mt-3 text-sm text-muted">{label}</p>
      </div>
    </div>
  );
}


export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="card mx-auto max-w-lg p-8 text-center">
      <p className="font-medium text-danger">Не удалось загрузить данные</p>
      <p className="mt-2 text-sm text-muted">{message}</p>
      {onRetry && <button className="button-primary mt-5" onClick={onRetry}>Повторить</button>}
    </div>
  );
}


export function EmptyState({ children }: { children: ReactNode }) {
  return <div className="card py-16 text-center text-sm text-muted">{children}</div>;
}
