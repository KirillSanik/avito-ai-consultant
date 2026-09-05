"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { AppHeader, EmptyState, ErrorState, PageLoader } from "@/components/ui";
import { applicationApi } from "@/lib/api";
import type { EnrollmentApplication } from "@/lib/types";


const tabs: Array<{ value: EnrollmentApplication["status"]; label: string }> = [
  { value: "pending", label: "На рассмотрении" },
  { value: "enrolled", label: "Принятые" },
  { value: "rejected", label: "Отклонённые" },
];


export function ApplicationsPanel({ courseId }: { courseId?: string }) {
  const queryClient = useQueryClient();
  const [status, setStatus] = useState<EnrollmentApplication["status"]>("pending");
  const applications = useQuery({
    queryKey: ["enrollment-applications", status, courseId ?? "all"],
    queryFn: () => applicationApi.list(status, courseId),
  });
  const decide = useMutation({
    mutationFn: ({
      id,
      decision,
    }: {
      id: number;
      decision: "enrolled" | "rejected";
    }) => applicationApi.decide(id, decision),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ["enrollment-applications"] }),
  });

  return (
    <div>
      <div className="mb-6 flex rounded-lg border border-border bg-secondary p-0.5">
        {tabs.map((tab) => (
          <button
            key={tab.value}
            type="button"
            onClick={() => setStatus(tab.value)}
            className={`rounded-md px-3 py-1.5 text-xs font-medium ${
              status === tab.value
                ? "bg-white text-foreground ring-1 ring-border"
                : "text-muted"
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>
      {applications.isLoading ? (
        <PageLoader label="Загружаем заявки…" />
      ) : applications.error ? (
        <ErrorState
          message={applications.error.message}
          onRetry={() => applications.refetch()}
        />
      ) : !applications.data?.length ? (
        <EmptyState>В этой категории заявок нет</EmptyState>
      ) : (
        <div className="space-y-3">
          {applications.data.map((application) => (
            <article
              key={application.id}
              className="card flex flex-wrap items-center gap-4 p-5"
            >
              <div className="grid h-10 w-10 place-items-center rounded-full bg-indigo-50 font-semibold text-accent">
                {application.student_name[0]}
              </div>
              <div className="min-w-[220px] flex-1">
                <h2 className="text-sm font-semibold">
                  {application.student_name}
                </h2>
                <p className="mt-1 text-xs text-muted">
                  {courseId ? application.student_login : `${application.course_title} · ${application.student_login}`}
                  {application.student_telegram
                    ? ` · @${application.student_telegram}`
                    : ""}
                </p>
                <p className="mt-1 text-[11px] text-muted">
                  {new Date(application.created_at).toLocaleString("ru-RU")}
                </p>
              </div>
              {application.status === "pending" && (
                <div className="flex gap-2">
                  <button
                    type="button"
                    className="button-success"
                    disabled={decide.isPending}
                    onClick={() =>
                      decide.mutate({
                        id: application.id,
                        decision: "enrolled",
                      })
                    }
                  >
                    Принять
                  </button>
                  <button
                    type="button"
                    className="button-secondary"
                    disabled={decide.isPending}
                    onClick={() =>
                      decide.mutate({
                        id: application.id,
                        decision: "rejected",
                      })
                    }
                  >
                    Отклонить
                  </button>
                </div>
              )}
            </article>
          ))}
          {decide.error && (
            <p className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-danger">
              {decide.error.message}
            </p>
          )}
        </div>
      )}
    </div>
  );
}


export function ApplicationsScreen({
  onBack,
  onLogout,
}: {
  onBack: () => void;
  onLogout: () => void;
}) {
  return (
    <div className="min-h-screen bg-background">
      <AppHeader
        role="methodist"
        accountRole="methodist"
        onRoleChange={(role) => {
          if (role === "reviewer") onBack();
        }}
        onLogout={onLogout}
      />
      <main className="mx-auto max-w-5xl px-5 py-8">
        <button
          type="button"
          className="mb-5 text-sm text-muted transition hover:text-foreground"
          onClick={onBack}
        >
          ← Курсы
        </button>
        <div className="mb-6">
          <p className="eyebrow">Приём на обучение</p>
          <h1 className="font-display text-4xl text-foreground">
            Заявки студентов
          </h1>
        </div>
        <ApplicationsPanel />
      </main>
    </div>
  );
}
