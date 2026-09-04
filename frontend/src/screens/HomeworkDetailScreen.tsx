"use client";

import { useQuery } from "@tanstack/react-query";

import { ErrorState, PageLoader } from "@/components/ui";
import { homeworkApi } from "@/lib/api";
import type { Course, HomeworkListItem, Role } from "@/lib/types";
import { MethodistHomework } from "./MethodistHomework";
import { ReviewerHomework } from "./ReviewerHomework";


export function HomeworkDetailScreen({
  course,
  homework,
  role,
  onBack,
}: {
  course: Course;
  homework: HomeworkListItem;
  role: Role;
  onBack: () => void;
}) {
  const assignment = useQuery({
    queryKey: ["assignment", homework.id, role],
    queryFn: () => homeworkApi.get(homework.id, role === "reviewer"),
  });

  return (
    <div className="min-h-screen bg-background">
      <header className="sticky top-0 z-20 border-b border-border bg-white px-5 py-3.5">
        <div className="mx-auto flex max-w-4xl items-center gap-3">
          <button className="text-sm text-muted transition hover:text-foreground" onClick={onBack}>← Назад</button>
          <span className="text-border">/</span>
          <span className="hidden truncate text-sm text-muted sm:block">{course.title}</span>
          <span className="hidden text-border sm:block">/</span>
          <span className="truncate text-sm font-medium">ДЗ #{homework.number ?? homework.id}</span>
          <span className="ml-auto rounded-md border border-border bg-secondary px-2 py-1 text-xs text-muted">
            {role === "reviewer" ? "Ревьюер" : "Методист"}
          </span>
        </div>
      </header>

      <main className="mx-auto max-w-4xl px-5 py-8">
        <div className="mb-7">
          <p className="eyebrow">Домашнее задание #{homework.number ?? homework.id}</p>
          <h1 className="font-display text-4xl leading-tight text-foreground">{homework.title}</h1>
          <p className="mt-1 text-sm text-muted">
            Дедлайн: {new Date(homework.deadline).toLocaleDateString("ru-RU", {
              day: "numeric",
              month: "long",
              year: "numeric",
            })}
          </p>
        </div>

        {assignment.isLoading ? (
          <PageLoader label="Загружаем домашнее задание…" />
        ) : assignment.error ? (
          <ErrorState message={assignment.error.message} onRetry={() => assignment.refetch()} />
        ) : assignment.data ? (
          role === "reviewer" ? (
            <ReviewerHomework
              assignment={assignment.data}
              listItem={homework}
              onRefresh={assignment.refetch}
            />
          ) : (
            <MethodistHomework
              key={assignment.data.id}
              assignment={assignment.data}
              onRefresh={assignment.refetch}
            />
          )
        ) : null}
      </main>
    </div>
  );
}
