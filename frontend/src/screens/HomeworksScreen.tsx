"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FormEvent, useState } from "react";

import { EmptyState, ErrorState, PageLoader, ProgressBar } from "@/components/ui";
import { XlsxImportCard } from "@/components/xlsx";
import { courseApi } from "@/lib/api";
import type { Course, CourseReviewer, Criterion, HomeworkListItem, Role, User } from "@/lib/types";
import { ApplicationsPanel } from "@/screens/ApplicationsScreen";


const currentTime = Date.now();


export function HomeworksScreen({
  course,
  role,
  currentUser,
  onBack,
  onSelect,
}: {
  course: Course;
  role: Role;
  currentUser?: User;
  onBack: () => void;
  onSelect: (homework: HomeworkListItem) => void;
}) {
  const [creating, setCreating] = useState(false);
  const [tab, setTab] = useState<"homeworks" | "applications">("homeworks");
  const homeworks = useQuery({
    queryKey: ["homeworks", course.id, role],
    queryFn: () => courseApi.homeworks(course.id, role === "reviewer"),
  });
  const canCreateHomework = role === "methodist";

  return (
    <div className="min-h-screen bg-background">
      <header className="sticky top-0 z-20 border-b border-border bg-white px-5 py-3.5">
        <div className="mx-auto flex max-w-5xl items-center gap-3">
          <button className="text-sm text-muted transition hover:text-foreground" onClick={onBack}>← Курсы</button>
          <span className="text-border">/</span>
          <span className="truncate text-sm font-medium">{course.title}</span>
          <span className="ml-auto rounded-md border border-border bg-secondary px-2 py-1 text-xs text-muted">
            {role === "reviewer" ? "Ревьюер" : "Методист"}
          </span>
        </div>
      </header>

      <main className="mx-auto max-w-5xl px-5 py-8">
        <div className="mb-7 flex flex-wrap items-end justify-between gap-4">
          <div>
            <p className="eyebrow">Поток {course.stream ?? 1} · {course.year}</p>
            <h1 className="font-display text-4xl text-foreground">
              {tab === "applications" ? "Заявки студентов" : "Домашние задания"}
            </h1>
            <p className="mt-1 text-sm text-muted">{course.students_count ?? "—"} студентов на курсе</p>
          </div>
          <div className="flex flex-wrap items-center gap-3">
            {canCreateHomework && (
              <button
                type="button"
                className="button-secondary"
                onClick={() => void courseApi.exportXlsx(course.id)}
              >
                Скачать XLSX
              </button>
            )}
            {canCreateHomework && tab === "homeworks" && (
              <button className="button-primary" onClick={() => setCreating(true)}>
                Создать домашнее задание
              </button>
            )}
          </div>
        </div>

        {canCreateHomework && (
          <div className="mb-6 flex rounded-lg border border-border bg-secondary p-0.5">
            <button
              type="button"
              onClick={() => setTab("homeworks")}
              className={`rounded-md px-3 py-1.5 text-xs font-medium ${
                tab === "homeworks" ? "bg-white text-foreground ring-1 ring-border" : "text-muted"
              }`}
            >
              Домашние задания
            </button>
            <button
              type="button"
              onClick={() => setTab("applications")}
              className={`rounded-md px-3 py-1.5 text-xs font-medium ${
                tab === "applications" ? "bg-white text-foreground ring-1 ring-border" : "text-muted"
              }`}
            >
              Заявки студентов
            </button>
          </div>
        )}

        <CourseDescriptionForm course={course} />

        {tab === "applications" && canCreateHomework ? (
          <ApplicationsPanel courseId={course.id} />
        ) : (
          <>
            {creating && canCreateHomework && (
              <CreateHomeworkForm
                courseId={course.id}
                onCancel={() => setCreating(false)}
                onCreated={() => setCreating(false)}
              />
            )}

            {role === "methodist" && (
              <CourseReviewersPanel courseId={course.id} currentUserId={currentUser?.id} />
            )}

            {homeworks.isLoading ? (
              <PageLoader label="Загружаем домашние задания…" />
            ) : homeworks.error ? (
              <ErrorState message={homeworks.error.message} onRetry={() => homeworks.refetch()} />
            ) : !homeworks.data?.length ? (
              <EmptyState>Для этого курса домашние задания ещё не добавлены</EmptyState>
            ) : (
              <div className="space-y-3">
                {homeworks.data.map((homework, index) => (
                  <HomeworkCard
                    key={homework.id}
                    homework={homework}
                    number={homework.number ?? index + 1}
                    role={role}
                    onSelect={() => onSelect(homework)}
                  />
                ))}
              </div>
            )}
          </>
        )}
      </main>
    </div>
  );
}


function CourseDescriptionForm({ course }: { course: Course }) {
  const queryClient = useQueryClient();
  const [description, setDescription] = useState(course.description ?? "");
  const save = useMutation({
    mutationFn: () => courseApi.updateDescription(course.id, description),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["courses"] });
    },
  });

  return (
    <section className="card mb-6 p-5">
      <p className="eyebrow">О курсе</p>
      <h2 className="mb-3 text-lg font-semibold">Описание для студентов</h2>
      <textarea
        rows={4}
        value={description}
        onChange={(event) => setDescription(event.target.value)}
      />
      <div className="mt-3 flex flex-wrap items-center gap-3">
        <button
          type="button"
          className="button-primary"
          disabled={save.isPending}
          onClick={() => save.mutate()}
        >
          {save.isPending ? "Сохраняем…" : "Сохранить описание"}
        </button>
        {save.isSuccess && <span className="text-xs text-success">Сохранено</span>}
        {save.error && <span className="text-xs text-danger">{save.error.message}</span>}
      </div>
    </section>
  );
}


function CreateHomeworkForm({
  courseId,
  onCancel,
  onCreated,
}: {
  courseId: number;
  onCancel: () => void;
  onCreated: () => void;
}) {
  const queryClient = useQueryClient();
  const [form, setForm] = useState({
    title: "",
    deadline: "2026-09-20T23:59",
    task_url: "",
    criteria_url: "",
    reviewer_guide: "Проверьте работу по критериям. AI-оценка является только черновиком.",
  });
  const [criteria, setCriteria] = useState<Criterion[]>([
    { title: "", max_score: 10, description: "" },
  ]);
  const [selectedReviewerIds, setSelectedReviewerIds] = useState<number[]>([]);
  const [pickerId, setPickerId] = useState("");
  const courseReviewers = useQuery({
    queryKey: ["course-reviewers", courseId],
    queryFn: () => courseApi.reviewers(courseId),
  });
  const criteriaTotal = criteria.reduce((sum, item) => sum + Number(item.max_score || 0), 0);
  const criteriaInvalid = criteriaTotal !== 100;
  const selectedReviewers = (courseReviewers.data ?? []).filter((item) =>
    selectedReviewerIds.includes(item.user_id),
  );
  const availableReviewers = (courseReviewers.data ?? []).filter(
    (item) => !selectedReviewerIds.includes(item.user_id),
  );
  const create = useMutation({
    mutationFn: () =>
      courseApi.createHomework(courseId, {
        title: form.title,
        deadline: form.deadline.length === 16 ? `${form.deadline}:00` : form.deadline,
        task_url: form.task_url,
        criteria_url: form.criteria_url.trim(),
        reviewer_guide: form.reviewer_guide,
        criteria: criteria.map((item) => ({
          title: item.title.trim(),
          max_score: item.max_score,
          description: item.description?.trim() ?? "",
        })),
        reviewer_user_ids: selectedReviewerIds,
      }),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["homeworks", courseId] }),
        queryClient.invalidateQueries({ queryKey: ["courses"] }),
      ]);
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
        <p className="eyebrow">Новое задание</p>
        <h2 className="text-lg font-semibold">Создание домашнего задания</h2>
      </div>
      <label className="sm:col-span-2">
        <span className="field-label">Название</span>
        <input
          value={form.title}
          onChange={(event) => setForm((current) => ({ ...current, title: event.target.value }))}
          placeholder="Исследование продуктовой метрики"
          required
          minLength={2}
        />
      </label>
      <label>
        <span className="field-label">Дедлайн</span>
        <input
          type="datetime-local"
          value={form.deadline}
          onChange={(event) => setForm((current) => ({ ...current, deadline: event.target.value }))}
          required
        />
      </label>
      <label>
        <span className="field-label">Ссылка на задание</span>
        <input
          type="url"
          value={form.task_url}
          onChange={(event) => setForm((current) => ({ ...current, task_url: event.target.value }))}
          placeholder="https://github.com/..."
          required
        />
      </label>
      <label className="sm:col-span-2">
        <span className="field-label">Ссылка на подробные критерии (необязательно)</span>
        <input
          value={form.criteria_url}
          onChange={(event) => setForm((current) => ({ ...current, criteria_url: event.target.value }))}
          placeholder="https://docs.google.com/..."
        />
      </label>
      <div className="sm:col-span-2 space-y-3">
        <div className="flex items-center justify-between">
          <span className="field-label mb-0">Критерии</span>
          <button
            type="button"
            className="text-xs font-medium text-accent hover:underline"
            onClick={() =>
              setCriteria((current) => [...current, { title: "", max_score: 10, description: "" }])
            }
          >
            + Добавить критерий
          </button>
        </div>
        <p className={`text-xs ${criteriaInvalid ? "text-danger" : "text-success"}`}>
          Сумма баллов: {criteriaTotal} / 100. Должно быть ровно 100.
        </p>
        {criteria.map((criterion, index) => (
          <div key={index} className="space-y-2 rounded-lg border border-border p-3">
            <div className="grid grid-cols-[1fr_100px_auto] gap-2">
              <input
                value={criterion.title}
                onChange={(event) =>
                  setCriteria((current) =>
                    current.map((item, itemIndex) =>
                      index === itemIndex ? { ...item, title: event.target.value } : item,
                    ),
                  )
                }
                placeholder="Название критерия"
                required
                minLength={2}
              />
              <input
                type="number"
                min={0}
                max={100}
                value={criterion.max_score}
                onChange={(event) =>
                  setCriteria((current) =>
                    current.map((item, itemIndex) =>
                      index === itemIndex ? { ...item, max_score: Number(event.target.value) } : item,
                    ),
                  )
                }
                required
              />
              <button
                type="button"
                className="text-xs text-muted hover:text-danger"
                disabled={criteria.length <= 1}
                onClick={() => setCriteria((current) => current.filter((_, itemIndex) => itemIndex !== index))}
              >
                Удалить
              </button>
            </div>
            <textarea
              rows={2}
              value={criterion.description ?? ""}
              placeholder="Описание критерия"
              onChange={(event) =>
                setCriteria((current) =>
                  current.map((item, itemIndex) =>
                    index === itemIndex ? { ...item, description: event.target.value } : item,
                  ),
                )
              }
            />
          </div>
        ))}
      </div>
      <div className="sm:col-span-2 space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <span className="field-label mb-0">Ревьюеры этого ДЗ</span>
          <button
            type="button"
            className="text-xs font-medium text-accent hover:underline"
            disabled={!courseReviewers.data?.length}
            onClick={() =>
              setSelectedReviewerIds((courseReviewers.data ?? []).map((item) => item.user_id))
            }
          >
            Добавить всех с курса
          </button>
        </div>
        {selectedReviewers.length ? (
          <ul className="flex flex-wrap gap-2">
            {selectedReviewers.map((reviewer) => (
              <li
                key={reviewer.user_id}
                className="flex items-center gap-2 rounded-lg border border-border bg-secondary px-3 py-1.5 text-sm"
              >
                <span>{reviewer.first_name} {reviewer.last_name}</span>
                <button
                  type="button"
                  className="text-xs text-muted hover:text-danger"
                  onClick={() =>
                    setSelectedReviewerIds((current) => current.filter((id) => id !== reviewer.user_id))
                  }
                >
                  Убрать
                </button>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-muted">Никто не выбран — можно добавить всех или выбрать из списка</p>
        )}
        {availableReviewers.length > 0 && (
          <div className="flex flex-wrap items-end gap-2">
            <label className="min-w-[220px] flex-1">
              <span className="field-label">Добавить ревьюера курса</span>
              <select value={pickerId} onChange={(event) => setPickerId(event.target.value)}>
                <option value="">Выберите ревьюера</option>
                {availableReviewers.map((reviewer) => (
                  <option key={reviewer.user_id} value={reviewer.user_id}>
                    {reviewer.first_name} {reviewer.last_name}
                  </option>
                ))}
              </select>
            </label>
            <button
              type="button"
              className="button-secondary"
              disabled={!pickerId}
              onClick={() => {
                setSelectedReviewerIds((current) => [...current, Number(pickerId)]);
                setPickerId("");
              }}
            >
              Добавить
            </button>
          </div>
        )}
      </div>
      <label className="sm:col-span-2">
        <span className="field-label">Инструкция ревьюеру</span>
        <textarea
          rows={3}
          value={form.reviewer_guide}
          onChange={(event) => setForm((current) => ({ ...current, reviewer_guide: event.target.value }))}
          required
          minLength={3}
        />
      </label>
      {create.error && (
        <p className="sm:col-span-2 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-danger">
          {create.error.message}
        </p>
      )}
      <div className="flex flex-wrap gap-2 sm:col-span-2">
        <button className="button-primary" disabled={create.isPending || criteriaInvalid}>
          {create.isPending ? "Сохраняем…" : "Сохранить задание"}
        </button>
        <button type="button" className="button-secondary" onClick={onCancel}>
          Отмена
        </button>
      </div>
    </form>
  );
}


function CourseReviewersPanel({
  courseId,
  currentUserId,
}: {
  courseId: number;
  currentUserId?: number;
}) {
  const queryClient = useQueryClient();
  const [selectedId, setSelectedId] = useState("");
  const assigned = useQuery({
    queryKey: ["course-reviewers", courseId],
    queryFn: () => courseApi.reviewers(courseId),
  });
  const catalog = useQuery({
    queryKey: ["reviewer-catalog"],
    queryFn: courseApi.reviewerCatalog,
  });
  const add = useMutation({
    mutationFn: (userId: number) => courseApi.addReviewer(courseId, userId),
    onSuccess: async () => {
      setSelectedId("");
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["course-reviewers", courseId] }),
        queryClient.invalidateQueries({ queryKey: ["courses"] }),
      ]);
    },
  });
  const remove = useMutation({
    mutationFn: (userId: number) => courseApi.removeReviewer(courseId, userId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["course-reviewers", courseId] }),
  });

  const assignedIds = new Set((assigned.data ?? []).map((item) => item.user_id));
  const available = (catalog.data ?? []).filter((user) => !assignedIds.has(user.id));

  function submit(event: FormEvent) {
    event.preventDefault();
    if (!selectedId) return;
    add.mutate(Number(selectedId));
  }

  return (
    <section className="card mb-6 p-5">
      <div className="mb-4">
        <p className="eyebrow">Команда курса</p>
        <h2 className="text-lg font-semibold">Ревьюеры</h2>
        <p className="mt-1 text-xs text-muted">
          Курс виден ревьюеру только после назначения
        </p>
      </div>

      {assigned.error ? (
        <ErrorState message={assigned.error.message} onRetry={() => assigned.refetch()} />
      ) : assigned.isLoading ? (
        <p className="mb-4 text-sm text-muted">Загружаем назначенных…</p>
      ) : assigned.data?.length ? (
        <ul className="mb-4 flex flex-wrap gap-2">
          {assigned.data.map((reviewer) => (
            <li
              key={reviewer.id}
              className="flex items-center gap-2 rounded-lg border border-border bg-secondary px-3 py-1.5 text-sm"
            >
              <span>
                {reviewerName(reviewer)}
                {reviewer.user_id === currentUserId ? " (вы)" : ""}
              </span>
              <button
                type="button"
                className="text-xs text-muted hover:text-danger"
                onClick={() => remove.mutate(reviewer.user_id)}
                disabled={remove.isPending}
              >
                Убрать
              </button>
            </li>
          ))}
        </ul>
      ) : (
        <p className="mb-4 text-sm text-muted">Пока никто не назначен — ревьюеры этот курс не увидят</p>
      )}

      <form className="flex flex-wrap items-end gap-3" onSubmit={submit}>
        <label className="min-w-[220px] flex-1">
          <span className="field-label">Существующие ревьюеры</span>
          <select
            value={selectedId}
            onChange={(event) => setSelectedId(event.target.value)}
            disabled={catalog.isLoading || !available.length}
          >
            <option value="">
              {catalog.isLoading
                ? "Загружаем список…"
                : available.length
                  ? "Выберите ревьюера"
                  : "Все ревьюеры уже назначены"}
            </option>
            {available.map((user) => (
              <option key={user.id} value={user.id}>
                {reviewerName(user)}
                {user.id === currentUserId ? " (вы)" : ""} @{user.telegram}
              </option>
            ))}
          </select>
        </label>
        <button className="button-primary" disabled={!selectedId || add.isPending}>
          {add.isPending ? "Добавляем…" : "Добавить ревьюера"}
        </button>
      </form>
      {add.error && (
        <p className="mt-3 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-danger">
          {add.error.message}
        </p>
      )}
      <div className="mt-4">
        <XlsxImportCard
          title="Импорт ревьюеров из XLSX"
          hint="Обязательная колонка login. Неизвестные аккаунты не создаются."
          onPreview={(file) => courseApi.importReviewers(courseId, file, false)}
          onConfirm={(file) => courseApi.importReviewers(courseId, file, true)}
          onApplied={async () => {
            await Promise.all([
              queryClient.invalidateQueries({ queryKey: ["course-reviewers", courseId] }),
              queryClient.invalidateQueries({ queryKey: ["courses"] }),
            ]);
          }}
        />
      </div>
    </section>
  );
}


function reviewerName(person: CourseReviewer | User) {
  return `${person.first_name} ${person.last_name}`.trim() || person.login;
}


function HomeworkCard({
  homework,
  number,
  role,
  onSelect,
}: {
  homework: HomeworkListItem;
  number: number;
  role: Role;
  onSelect: () => void;
}) {
  const deadline = new Date(homework.deadline);
  const isPast = deadline.getTime() < currentTime;
  const checked = role === "reviewer" ? homework.reviewer_checked ?? homework.reviewed : homework.reviewed;
  const total = role === "reviewer" ? homework.reviewer_total ?? homework.total : homework.total;
  const percent = total > 0 ? Math.round((checked / total) * 100) : 0;
  const tone = role === "reviewer"
    ? percent === 100 ? "success" : "accent"
    : percent >= 80 ? "success" : percent >= 40 ? "warning" : "danger";

  return (
    <button
      onClick={onSelect}
      className="card group w-full p-5 text-left transition hover:border-accent hover:shadow-md"
    >
      <div className="flex items-start gap-4">
        <div className="grid h-10 w-10 shrink-0 place-items-center rounded-lg border border-border bg-secondary font-mono text-xs font-semibold text-muted">
          #{number}
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-start justify-between gap-4">
            <div>
              <h2 className="text-sm font-semibold text-foreground transition group-hover:text-primary">{homework.title}</h2>
              <span className={`mt-2 inline-block rounded-md px-2 py-0.5 text-xs font-medium ${
                isPast ? "bg-red-50 text-danger" : "bg-emerald-50 text-success"
              }`}>
                Дедлайн: {deadline.toLocaleDateString("ru-RU", { day: "numeric", month: "short", year: "numeric" })}
              </span>
            </div>
            <span className="text-muted transition group-hover:translate-x-0.5 group-hover:text-accent">→</span>
          </div>
          <div className="mt-4 rounded-lg bg-secondary p-3">
            <div className="mb-2 flex items-center justify-between text-xs">
              <span className="text-muted">{role === "reviewer" ? "Мои проверки" : "Глобальный прогресс"}</span>
              <span className="font-mono font-semibold">{checked} / {total}</span>
            </div>
            <ProgressBar value={checked} total={total} tone={tone} />
          </div>
        </div>
      </div>
    </button>
  );
}
