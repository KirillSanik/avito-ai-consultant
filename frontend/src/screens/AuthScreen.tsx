"use client";

import { useMutation } from "@tanstack/react-query";
import { FormEvent, useState } from "react";

import { Logo } from "@/components/ui";
import { authApi, setAuthToken } from "@/lib/api";
import type { AuthResponse, Role } from "@/lib/types";


type Mode = "login" | "register";

export function AuthScreen({ onAuthenticated }: { onAuthenticated: (auth: AuthResponse) => void }) {
  const [mode, setMode] = useState<Mode>("login");
  const [form, setForm] = useState({
    login: "",
    password: "",
    first_name: "",
    last_name: "",
    telegram: "",
    role: "reviewer" as Role,
  });

  const auth = useMutation({
    mutationFn: () =>
      mode === "login"
        ? authApi.login(form.login, form.password)
        : authApi.register(form),
    onSuccess: (response) => {
      setAuthToken(response.token);
      onAuthenticated(response);
    },
  });

  function update<Key extends keyof typeof form>(key: Key, value: (typeof form)[Key]) {
    setForm((current) => ({ ...current, [key]: value }));
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    auth.mutate();
  }

  return (
    <main className="grid min-h-screen place-items-center bg-background px-4 py-8">
      <div className="w-full max-w-md">
        <div className="mb-8 flex justify-center"><Logo /></div>

        <section className="card p-7 sm:p-8">
          <div className="mb-6">
            <p className="eyebrow">{mode === "login" ? "Добро пожаловать" : "Новый аккаунт"}</p>
            <h1 className="font-display text-3xl text-foreground">
              {mode === "login" ? "Войти в аккаунт" : "Регистрация"}
            </h1>
          </div>

          <form className="space-y-4" onSubmit={submit}>
            {mode === "register" && (
              <div className="grid grid-cols-2 gap-3">
                <Field label="Имя">
                  <input
                    value={form.first_name}
                    onChange={(event) => update("first_name", event.target.value)}
                    placeholder="Иван"
                    required
                  />
                </Field>
                <Field label="Фамилия">
                  <input
                    value={form.last_name}
                    onChange={(event) => update("last_name", event.target.value)}
                    placeholder="Иванов"
                    required
                  />
                </Field>
              </div>
            )}

            <Field label="Логин">
              <input
                autoComplete="username"
                value={form.login}
                onChange={(event) => update("login", event.target.value)}
                placeholder="reviewer"
                required
              />
            </Field>
            <Field label="Пароль">
              <input
                type="password"
                autoComplete={mode === "login" ? "current-password" : "new-password"}
                value={form.password}
                onChange={(event) => update("password", event.target.value)}
                placeholder="••••••••"
                minLength={4}
                required
              />
            </Field>

            {mode === "register" && (
              <>
                <Field label="Telegram">
                  <div className="relative">
                    <span className="absolute left-3.5 top-1/2 -translate-y-1/2 text-muted">@</span>
                    <input
                      className="pl-8"
                      value={form.telegram}
                      onChange={(event) => update("telegram", event.target.value.replace(/^@/, ""))}
                      placeholder="username"
                      required
                    />
                  </div>
                </Field>
                <div>
                  <span className="field-label">Роль</span>
                  <div className="grid grid-cols-2 gap-2">
                    {(["reviewer", "methodist"] as Role[]).map((role) => (
                      <button
                        key={role}
                        type="button"
                        onClick={() => update("role", role)}
                        className={`rounded-lg border px-3 py-2.5 text-sm font-medium transition ${
                          form.role === role
                            ? "border-primary bg-primary text-white"
                            : "border-border bg-secondary text-muted hover:border-accent"
                        }`}
                      >
                        {role === "reviewer" ? "Ревьюер" : "Методист"}
                      </button>
                    ))}
                  </div>
                </div>
              </>
            )}

            {auth.error && (
              <p className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-danger">
                {auth.error.message}
              </p>
            )}

            <button className="button-primary w-full" disabled={auth.isPending}>
              {auth.isPending ? "Подождите…" : mode === "login" ? "Войти" : "Создать аккаунт"}
            </button>
          </form>

          <div className="mt-6 border-t border-border pt-5 text-center text-sm text-muted">
            {mode === "login" ? "Нет аккаунта? " : "Уже есть аккаунт? "}
            <button
              className="font-medium text-accent hover:underline"
              onClick={() => {
                setMode(mode === "login" ? "register" : "login");
                auth.reset();
              }}
            >
              {mode === "login" ? "Зарегистрироваться" : "Войти"}
            </button>
          </div>
        </section>

        {mode === "login" && (
          <p className="mt-5 text-center text-xs text-muted">
            Демо: reviewer / reviewer или methodist / methodist
          </p>
        )}
      </div>
    </main>
  );
}


function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="field-label">{label}</span>
      {children}
    </label>
  );
}
