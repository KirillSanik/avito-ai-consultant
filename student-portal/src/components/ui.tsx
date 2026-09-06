import type { ReactNode } from "react";


export function Logo() {
  return (
    <div className="flex items-center gap-3">
      <div className="grid h-10 w-10 place-items-center rounded-xl bg-primary text-lg font-bold text-white">
        S
      </div>
      <div>
        <p className="font-display text-xl leading-none">ReviewDesk</p>
        <p className="mt-1 text-[10px] uppercase tracking-[0.18em] text-muted">
          Студентам
        </p>
      </div>
    </div>
  );
}


export function Header({
  children,
  onLogout,
}: {
  children?: ReactNode;
  onLogout: () => void;
}) {
  return (
    <header className="sticky top-0 z-20 border-b border-border bg-white/95 px-5 py-3 backdrop-blur">
      <div className="mx-auto flex max-w-6xl items-center justify-between gap-4">
        <Logo />
        <div className="flex items-center gap-4">
          {children}
          <button
            type="button"
            className="text-xs text-muted transition hover:text-danger"
            onClick={onLogout}
          >
            Выйти
          </button>
        </div>
      </div>
    </header>
  );
}


export function Loader({ label = "Загружаем…" }: { label?: string }) {
  return (
    <div className="grid min-h-48 place-items-center text-sm text-muted">
      {label}
    </div>
  );
}


export function Empty({ children }: { children: ReactNode }) {
  return (
    <div className="card py-12 text-center text-sm text-muted">{children}</div>
  );
}


export function ErrorMessage({
  error,
  retry,
}: {
  error: Error;
  retry?: () => void;
}) {
  return (
    <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-danger">
      {error.message}
      {retry && (
        <button className="ml-3 underline" onClick={retry}>
          Повторить
        </button>
      )}
    </div>
  );
}
