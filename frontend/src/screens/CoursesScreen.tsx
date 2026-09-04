"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FormEvent, useState } from "react";

import { AppHeader, EmptyState, ErrorState, PageLoader } from "@/components/ui";
import { courseApi } from "@/lib/api";
import type { Course, Role } from "@/lib/types";


const fallbackCovers = ["#3B6EF5", "#8B5CF6", "#059669", "#DC2626", "#D97706", "#0891B2"];

export function CoursesScreen({
  role,
  accountRole,
  onRoleChange,
  onSelect,
  onApplications,
  onLogout,
}: {
  role: Role;
  accountRole: Role;
  onRoleChange: (role: Role) => void;
  onSelect: (course: Course) => void;
  onApplications: () => void;
  onLogout: () => void;
}) {
  const [showPast, setShowPast] = useState(false);
  const [creating, setCreating] = useState(false);
  const canCreateCourse = accountRole === "methodist" && role === "methodist";
  const courses = useQuery({
    queryKey: ["courses", role],
    queryFn: () => courseApi.list(role === "reviewer"),
    placeholderData: (previous) => previous,
  });

  if (courses.isLoading) return <PageLoader label="Загружаем курсы…" />;

  return (
    <div className="min-h-screen bg-background">
      <AppHeader
        role={role}
        accountRole={accountRole}
        onRoleChange={(nextRole) => {
          if (nextRole !== "methodist") setCreating(false);
          onRoleChange(nextRole);
        }}
        onLogout={onLogout}
      />
      <main className="mx-auto max-w-6xl px-5 py-8">
        <div className="mb-7 flex flex-wrap items-end justify-between gap-4">
          <div>
            <p className="eyebrow">Учебная платформа</p>
            <h1 className="font-display text-4xl text-foreground">Курсы</h1>
            <p className="mt-1 text-sm text-muted">
              {role === "reviewer" ? "Курсы, где вы назначены ревьюером" : "Все доступные курсы и потоки"}
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-3">
            {canCreateCourse && (
              <>
                <button className="button-secondary" onClick={onApplications}>
                  Заявки студентов
                </button>
                <button className="button-primary" onClick={() => setCreating(true)}>
                  Создать курс
                </button>
              </>
            )}
            <div className="flex rounded-lg border border-border bg-secondary p-0.5">
              <button
                onClick={() => setShowPast(false)}
                className={`rounded-md px-4 py-1.5 text-xs font-medium ${!showPast ? "bg-white text-foreground ring-1 ring-border" : "text-muted"}`}
              >
                Активные
              </button>
              <button
                onClick={() => setShowPast(true)}
                className={`rounded-md px-4 py-1.5 text-xs font-medium ${showPast ? "bg-white text-foreground ring-1 ring-border" : "text-muted"}`}
              >
                Прошедшие
              </button>
            </div>
          </div>
        </div>

        {creating && canCreateCourse && (
          <CreateCourseForm
            onCancel={() => setCreating(false)}
            onCreated={() => setCreating(false)}
          />
        )}

        {courses.error ? (
          <ErrorState message={courses.error.message} onRetry={() => courses.refetch()} />
        ) : (
          <CourseGrid
            courses={(courses.data ?? []).filter((course) => Boolean(course.active ?? true) !== showPast)}
            onSelect={onSelect}
            canExport={canCreateCourse}
          />
        )}
      </main>
    </div>
  );
}


function CreateCourseForm({
  onCancel,
  onCreated,
}: {
  onCancel: () => void;
  onCreated: () => void;
}) {
  const queryClient = useQueryClient();
  const [form, setForm] = useState({
    title: "",
    year: 2026,
    cohort: "",
    stream: 1,
    cover_color: fallbackCovers[0],
    students_count: 0,
    description: "",
    capacity: 30,
  });
  const create = useMutation({
    mutationFn: () => courseApi.create(form),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["courses"] });
      onCreated();
    },
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    create.mutate();
  }

  return (
    <form className="card mb-6 grid gap-4 p-5 sm:grid-cols-2" onSubmit={submit}>
      <div className="sm:col-span-2">
        <p className="eyebrow">Новый курс</p>
        <h2 className="text-lg font-semibold">Создание курса</h2>
      </div>
      <label className="sm:col-span-2">
        <span className="field-label">Название</span>
        <input
          value={form.title}
          onChange={(event) => setForm((current) => ({ ...current, title: event.target.value }))}
          placeholder="Python для анализа данных"
          required
          minLength={2}
        />
      </label>
      <label className="sm:col-span-2">
        <span className="field-label">Описание для студентов</span>
        <textarea
          rows={3}
          value={form.description}
          onChange={(event) =>
            setForm((current) => ({ ...current, description: event.target.value }))
          }
          placeholder="Чему научится студент и как устроен курс"
        />
      </label>
      <label>
        <span className="field-label">Поток</span>
        <input
          type="number"
          min={1}
          max={99}
          value={form.stream}
          onChange={(event) => setForm((current) => ({ ...current, stream: Number(event.target.value) }))}
          required
        />
      </label>
      <label>
        <span className="field-label">Год запуска</span>
        <input
          type="number"
          min={2000}
          max={2100}
          value={form.year}
          onChange={(event) => setForm((current) => ({ ...current, year: Number(event.target.value) }))}
          required
        />
      </label>
      <label>
        <span className="field-label">Название потока</span>
        <input
          value={form.cohort}
          onChange={(event) => setForm((current) => ({ ...current, cohort: event.target.value }))}
          placeholder="Осенний поток"
          required
          minLength={2}
        />
      </label>
      <label>
        <span className="field-label">Студентов</span>
        <input
          type="number"
          min={0}
          value={form.students_count}
          onChange={(event) => setForm((current) => ({ ...current, students_count: Number(event.target.value) }))}
        />
      </label>
      <label>
        <span className="field-label">Количество мест</span>
        <input
          type="number"
          min={1}
          value={form.capacity}
          onChange={(event) =>
            setForm((current) => ({ ...current, capacity: Number(event.target.value) }))
          }
          required
        />
      </label>
      <div className="sm:col-span-2">
        <span className="field-label">Цвет карточки</span>
        <div className="flex flex-wrap gap-2">
          {fallbackCovers.map((color) => (
            <button
              key={color}
              type="button"
              aria-label={`Цвет ${color}`}
              onClick={() => setForm((current) => ({ ...current, cover_color: color }))}
              className={`h-8 w-8 rounded-full border ${form.cover_color === color ? "ring-2 ring-accent ring-offset-2" : "border-white"}`}
              style={{ background: color }}
            />
          ))}
        </div>
      </div>
      {create.error && (
        <p className="sm:col-span-2 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-danger">
          {create.error.message}
        </p>
      )}
      <div className="flex flex-wrap gap-2 sm:col-span-2">
        <button className="button-primary" disabled={create.isPending}>
          {create.isPending ? "Сохраняем…" : "Сохранить курс"}
        </button>
        <button type="button" className="button-secondary" onClick={onCancel}>
          Отмена
        </button>
      </div>
    </form>
  );
}


function CourseGrid({
  courses,
  onSelect,
  canExport,
}: {
  courses: Course[];
  onSelect: (course: Course) => void;
  canExport: boolean;
}) {
  if (!courses.length) return <EmptyState>В этой категории пока нет курсов</EmptyState>;

  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
      {courses.map((course, index) => {
        const cover = course.cover_color ?? fallbackCovers[index % fallbackCovers.length];
        const stream = course.stream ?? Number(course.cohort.match(/\d+/)?.[0] ?? 1);
        return (
          <article
            key={course.id}
            className="group overflow-hidden rounded-xl border border-border bg-white text-left transition hover:-translate-y-0.5 hover:border-accent hover:shadow-md"
          >
            <button
              type="button"
              onClick={() => onSelect(course)}
              className="w-full text-left"
            >
              <div
                className="relative flex aspect-[1.8] items-end p-4"
                style={{ background: `linear-gradient(135deg, ${cover}, ${cover}99)` }}
              >
                <span className="absolute right-3 top-3 rounded-full bg-white/20 px-2 py-0.5 text-[10px] font-medium text-white">
                  {course.active ?? true ? "Активный" : "Завершён"}
                </span>
                <span className="font-mono text-xs text-white/75">{course.assignments_count} ДЗ</span>
              </div>
              <div className="p-4">
                <h2 className="min-h-10 text-sm font-semibold leading-5 text-foreground transition group-hover:text-primary">
                  {course.title}
                </h2>
                <div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-muted">
                  <span>{course.students_count ?? "—"} студентов</span>
                  <span className="h-1 w-1 rounded-full bg-border" />
                  <span>Поток {stream}</span>
                  <span className="h-1 w-1 rounded-full bg-border" />
                  <span>{course.year}</span>
                </div>
              </div>
            </button>
            {canExport && (
              <div className="border-t border-border px-4 py-3">
                <button
                  type="button"
                  className="text-xs font-medium text-accent hover:underline"
                  onClick={() => void courseApi.exportXlsx(course.id)}
                >
                  Скачать XLSX
                </button>
              </div>
            )}
          </article>
        );
      })}
    </div>
  );
}
