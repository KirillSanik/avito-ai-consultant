"use client";

import {
  ColumnDef,
  flexRender,
  getCoreRowModel,
  useReactTable,
} from "@tanstack/react-table";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FormEvent, useMemo, useState } from "react";


const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

type Role = "reviewer" | "methodist";
type Course = { id: number; title: string; year: number; cohort: string; assignments_count: number };
type AssignmentListItem = { id: number; title: string; deadline: string; total: number; reviewed: number };
type Criterion = { title: string; max_score: number };
type DraftScore = { criterion: string; score: number; max_score: number; comment: string };
type Submission = {
  id: number;
  student_name: string;
  work_url: string;
  stepik_url: string;
  status: string;
  reviewer: string | null;
  score: number | null;
  summary: string | null;
  integrity_flag: string | null;
  ai_draft: {
    scores: DraftScore[];
    total: number;
    summary: string;
    integrity: { confidence: number; reason: string };
  } | null;
};
type Assignment = {
  id: number;
  course_id: number;
  title: string;
  deadline: string;
  task_url: string;
  criteria: Criterion[];
  reviewer_guide: string;
  submissions: Submission[];
};
type Dashboard = {
  total: number;
  reviewed: number;
  in_progress: number;
  reviewers: { name: string; reviewed: number; active: number; anomaly: boolean }[];
  clarifications: {
    id: number;
    assignment_id: number;
    author: string;
    message: string;
    status: string;
    created_at: string;
  }[];
};


async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({ detail: "Ошибка API" }));
    throw new Error(body.detail ?? "Ошибка API");
  }
  return response.json();
}


function Status({ value }: { value: string }) {
  const labels: Record<string, string> = {
    pending: "Ожидает",
    in_review: "На проверке",
    reviewed: "Проверено",
  };
  const classes =
    value === "reviewed"
      ? "bg-emerald-50 text-emerald-700"
      : value === "in_review"
        ? "bg-amber-50 text-amber-700"
        : "bg-slate-100 text-slate-600";
  return <span className={`rounded-full px-2.5 py-1 text-xs font-semibold ${classes}`}>{labels[value]}</span>;
}


function Login({ onLogin }: { onLogin: (role: Role) => void }) {
  return (
    <main className="grid min-h-screen place-items-center px-5">
      <section className="panel w-full max-w-4xl overflow-hidden">
        <div className="grid md:grid-cols-[1.1fr_0.9fr]">
          <div className="bg-ink p-10 text-white md:p-14">
            <p className="mb-16 text-sm font-bold tracking-[0.24em]">AVITO EDUCATION</p>
            <h1 className="max-w-lg text-4xl font-semibold leading-tight md:text-5xl">
              Проверка работ без лишней рутины
            </h1>
            <p className="mt-6 max-w-md text-base leading-7 text-slate-300">
              AI готовит черновик по критериям. Финальные баллы и обратная связь всегда остаются за человеком.
            </p>
          </div>
          <div className="flex flex-col justify-center p-8 md:p-12">
            <p className="label">Демо-вход</p>
            <h2 className="text-2xl font-semibold">Выберите рабочее место</h2>
            <p className="mt-2 text-sm leading-6 text-slate-500">Авторизация для PoC заменена выбором роли.</p>
            <div className="mt-8 grid gap-3">
              <button className="button-primary py-4 text-left" onClick={() => onLogin("reviewer")}>
                Войти как ревьюер
              </button>
              <button className="button-secondary py-4 text-left" onClick={() => onLogin("methodist")}>
                Войти как методист
              </button>
            </div>
          </div>
        </div>
      </section>
    </main>
  );
}


function Sidebar({
  role,
  courses,
  selectedCourse,
  onCourse,
  onLogout,
}: {
  role: Role;
  courses: Course[];
  selectedCourse?: number;
  onCourse: (id: number) => void;
  onLogout: () => void;
}) {
  return (
    <aside className="border-r border-line bg-ink p-5 text-white lg:min-h-screen">
      <div className="flex items-center justify-between lg:block">
        <div>
          <p className="text-xs font-bold tracking-[0.2em] text-emerald-300">AI REVIEWER</p>
          <p className="mt-2 text-sm text-slate-300">{role === "reviewer" ? "Ревьюер" : "Методист"}</p>
        </div>
        <button className="text-xs text-slate-400 hover:text-white lg:hidden" onClick={onLogout}>Выйти</button>
      </div>
      <nav className="mt-8 grid gap-2">
        <p className="mb-2 text-xs font-bold uppercase tracking-wider text-slate-500">Курсы</p>
        {courses.map((course) => (
          <button
            key={course.id}
            onClick={() => onCourse(course.id)}
            className={`rounded-xl p-3 text-left text-sm transition ${
              selectedCourse === course.id ? "bg-white text-ink" : "text-slate-300 hover:bg-white/10"
            }`}
          >
            <span className="block font-semibold">{course.title}</span>
            <span className={`mt-1 block text-xs ${selectedCourse === course.id ? "text-slate-500" : "text-slate-500"}`}>
              {course.year} · {course.cohort}
            </span>
          </button>
        ))}
      </nav>
      <button className="mt-10 hidden text-xs text-slate-400 hover:text-white lg:block" onClick={onLogout}>
        Выйти из демо
      </button>
    </aside>
  );
}


function SubmissionTable({
  submissions,
  selectedId,
  onSelect,
}: {
  submissions: Submission[];
  selectedId?: number;
  onSelect: (item: Submission) => void;
}) {
  const columns = useMemo<ColumnDef<Submission>[]>(
    () => [
      { accessorKey: "student_name", header: "Студент" },
      {
        id: "links",
        header: "Материалы",
        cell: ({ row }) => (
          <div className="flex gap-3">
            <a className="text-brand underline" href={row.original.work_url} target="_blank">GitHub</a>
            <a className="text-brand underline" href={row.original.stepik_url} target="_blank">Stepik</a>
          </div>
        ),
      },
      { accessorKey: "reviewer", header: "Ревьюер", cell: ({ getValue }) => getValue<string>() || "—" },
      { accessorKey: "status", header: "Статус", cell: ({ getValue }) => <Status value={getValue<string>()} /> },
      { accessorKey: "score", header: "Баллы", cell: ({ getValue }) => getValue<number>() ?? "—" },
    ],
    [],
  );
  const table = useReactTable({ data: submissions, columns, getCoreRowModel: getCoreRowModel() });

  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[720px] border-collapse text-left text-sm">
        <thead className="border-y border-line bg-stone-50 text-xs uppercase tracking-wider text-slate-500">
          {table.getHeaderGroups().map((group) => (
            <tr key={group.id}>
              {group.headers.map((header) => (
                <th key={header.id} className="px-4 py-3">
                  {flexRender(header.column.columnDef.header, header.getContext())}
                </th>
              ))}
            </tr>
          ))}
        </thead>
        <tbody>
          {table.getRowModel().rows.map((row) => (
            <tr
              key={row.id}
              onClick={() => onSelect(row.original)}
              className={`cursor-pointer border-b border-line transition hover:bg-emerald-50/50 ${
                selectedId === row.original.id ? "bg-emerald-50" : ""
              }`}
            >
              {row.getVisibleCells().map((cell) => (
                <td key={cell.id} className="px-4 py-4">
                  {flexRender(cell.column.columnDef.cell, cell.getContext())}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}


function ReviewPanel({
  submission,
  assignmentId,
  onNext,
}: {
  submission: Submission;
  assignmentId: number;
  onNext: (submission: Submission) => void;
}) {
  const queryClient = useQueryClient();
  const [score, setScore] = useState(submission.score ?? submission.ai_draft?.total ?? 0);
  const [summary, setSummary] = useState(submission.summary ?? submission.ai_draft?.summary ?? "");
  const [integrity, setIntegrity] = useState(submission.integrity_flag ?? "");
  const [clarification, setClarification] = useState("");

  const refresh = () => queryClient.invalidateQueries({ queryKey: ["assignment", assignmentId] });
  const draft = useMutation({
    mutationFn: () => api<Submission>(`/api/submissions/${submission.id}/ai-draft`, { method: "POST" }),
    onSuccess: (item) => {
      setScore(item.ai_draft?.total ?? 0);
      setSummary(item.ai_draft?.summary ?? "");
      setIntegrity(item.integrity_flag ?? "");
      refresh();
    },
  });
  const save = useMutation({
    mutationFn: () =>
      api<Submission>(`/api/submissions/${submission.id}/review`, {
        method: "PUT",
        body: JSON.stringify({ score, summary, integrity_flag: integrity || null }),
      }),
    onSuccess: refresh,
  });
  const next = useMutation({
    mutationFn: () => api<Submission>(`/api/assignments/${assignmentId}/next`),
    onSuccess: (item) => {
      refresh();
      onNext(item);
    },
  });
  const clarify = useMutation({
    mutationFn: () =>
      api(`/api/assignments/${assignmentId}/clarifications`, {
        method: "POST",
        body: JSON.stringify({ message: clarification }),
      }),
    onSuccess: () => setClarification(""),
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    save.mutate();
  }

  return (
    <section className="panel p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="label">Текущая работа</p>
          <h3 className="text-xl font-semibold">{submission.student_name}</h3>
        </div>
        <Status value={submission.status} />
      </div>
      <details className="mt-5 rounded-xl border border-line p-3">
        <summary className="cursor-pointer text-sm font-semibold">Уточнить условие или критерии</summary>
        <textarea
          className="mt-3 min-h-20 w-full rounded-lg border border-line p-3 text-sm"
          value={clarification}
          onChange={(event) => setClarification(event.target.value)}
          placeholder="Опишите вопрос методисту"
        />
        <button
          className="button-secondary mt-2"
          disabled={clarification.trim().length < 5 || clarify.isPending}
          onClick={() => clarify.mutate()}
        >
          Направить методисту
        </button>
        {clarify.isSuccess && <span className="ml-3 text-xs text-emerald-700">Отправлено</span>}
      </details>

      {!submission.ai_draft ? (
        <div className="mt-6 rounded-xl border border-dashed border-line p-6 text-center">
          <p className="text-sm text-slate-600">Черновик проверки ещё не сформирован.</p>
          <button className="button-primary mt-4" disabled={draft.isPending} onClick={() => draft.mutate()}>
            {draft.isPending ? "Анализируем…" : "Сформировать AI-черновик"}
          </button>
        </div>
      ) : (
        <form className="mt-6 grid gap-5" onSubmit={submit}>
          <div>
            <p className="label">Разбалловка AI</p>
            <div className="grid gap-2">
              {submission.ai_draft.scores.map((item) => (
                <div key={item.criterion} className="rounded-xl bg-stone-50 p-3">
                  <div className="flex justify-between gap-3 text-sm font-semibold">
                    <span>{item.criterion}</span><span>{item.score}/{item.max_score}</span>
                  </div>
                  <p className="mt-1 text-xs leading-5 text-slate-500">{item.comment}</p>
                </div>
              ))}
            </div>
          </div>
          <label>
            <span className="label">Итоговый балл</span>
            <input
              className="w-full rounded-lg border border-line px-3 py-2"
              type="number"
              min={0}
              max={100}
              value={score}
              onChange={(event) => setScore(Number(event.target.value))}
            />
          </label>
          <label>
            <span className="label">Короткий итог</span>
            <textarea
              className="min-h-28 w-full rounded-lg border border-line px-3 py-2"
              value={summary}
              onChange={(event) => setSummary(event.target.value)}
              required
            />
          </label>
          <label>
            <span className="label">Нарушение самостоятельности</span>
            <textarea
              className="min-h-20 w-full rounded-lg border border-line px-3 py-2"
              value={integrity}
              onChange={(event) => setIntegrity(event.target.value)}
              placeholder={submission.ai_draft.integrity.reason}
            />
            <span className="mt-1 block text-xs text-slate-500">
              Уверенность сигнала: {Math.round(submission.ai_draft.integrity.confidence * 100)}%. Решение принимает ревьюер.
            </span>
          </label>
          <div className="flex flex-wrap gap-2">
            <button className="button-primary" disabled={save.isPending}>Завершить проверку</button>
            <button
              className="button-secondary"
              type="button"
              disabled={next.isPending}
              onClick={() => next.mutate()}
            >
              Получить следующего
            </button>
            {submission.status === "reviewed" && (
              <a className="button-secondary" href={`${API_URL}/api/submissions/${submission.id}/report.pdf`}>
                Скачать PDF
              </a>
            )}
          </div>
          {(draft.error || save.error || next.error) && (
            <p className="text-sm text-red-600">{(draft.error || save.error || next.error)?.message}</p>
          )}
        </form>
      )}
    </section>
  );
}


function MethodistDashboard({ assignment }: { assignment?: Assignment }) {
  const queryClient = useQueryClient();
  const dashboard = useQuery({ queryKey: ["dashboard"], queryFn: () => api<Dashboard>("/api/dashboard") });
  const [guide, setGuide] = useState(assignment?.reviewer_guide ?? "");
  const [criteria, setCriteria] = useState<Criterion[]>(assignment?.criteria ?? []);
  const update = useMutation({
    mutationFn: () =>
      api(`/api/assignments/${assignment?.id}/criteria`, {
        method: "PUT",
        body: JSON.stringify({ criteria, reviewer_guide: guide }),
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["assignment", assignment?.id] }),
  });
  const reminder = useMutation({
    mutationFn: () =>
      api<{ status: string }>(`/api/assignments/${assignment?.id}/deadline-reminder`, {
        method: "POST",
      }),
  });

  if (dashboard.isLoading) return <p>Загрузка аналитики…</p>;
  if (dashboard.error) return <p className="text-red-600">{dashboard.error.message}</p>;
  const data = dashboard.data!;

  return (
    <div className="grid gap-5 xl:grid-cols-[1.25fr_0.75fr]">
      <section className="panel overflow-hidden">
        <div className="p-5">
          <p className="label">Команда</p>
          <h2 className="text-xl font-semibold">Прогресс ревьюеров</h2>
        </div>
        <div className="grid grid-cols-3 border-y border-line bg-stone-50">
          {[
            ["Всего", data.total],
            ["Проверено", data.reviewed],
            ["В работе", data.in_progress],
          ].map(([label, value]) => (
            <div key={label} className="border-r border-line p-5 last:border-r-0">
              <p className="text-3xl font-semibold">{value}</p><p className="mt-1 text-xs text-slate-500">{label}</p>
            </div>
          ))}
        </div>
        <div className="divide-y divide-line">
          {data.reviewers.map((reviewer) => (
            <div key={reviewer.name} className="flex items-center justify-between gap-4 p-5">
              <div>
                <p className="font-semibold">{reviewer.name}</p>
                <p className="mt-1 text-xs text-slate-500">
                  Проверено: {reviewer.reviewed} · В работе: {reviewer.active}
                </p>
              </div>
              {reviewer.anomaly ? (
                <span className="rounded-full bg-amber-50 px-3 py-1 text-xs font-semibold text-warning">Проверьте нагрузку</span>
              ) : <span className="text-xs text-emerald-700">В норме</span>}
            </div>
          ))}
        </div>
        {data.clarifications.length > 0 && (
          <div className="border-t border-line p-5">
            <p className="label">Вопросы по критериям</p>
            <div className="mt-3 grid gap-2">
              {data.clarifications.map((item) => (
                <div key={item.id} className="rounded-xl bg-amber-50 p-3 text-sm">
                  <p className="font-semibold">{item.author}</p>
                  <p className="mt-1 leading-5 text-slate-600">{item.message}</p>
                </div>
              ))}
            </div>
          </div>
        )}
      </section>
      <section className="panel p-5">
        <p className="label">Методичка</p>
        <h2 className="text-xl font-semibold">Критерии и инструкция</h2>
        <div className="mt-5 grid gap-2">
          {criteria.map((criterion, index) => (
            <div key={`${criterion.title}-${index}`} className="grid grid-cols-[1fr_88px] gap-2">
              <input
                aria-label={`Критерий ${index + 1}`}
                className="rounded-lg border border-line px-3 py-2 text-sm"
                value={criterion.title}
                onChange={(event) =>
                  setCriteria((items) =>
                    items.map((item, itemIndex) =>
                      itemIndex === index ? { ...item, title: event.target.value } : item,
                    ),
                  )
                }
              />
              <input
                aria-label={`Максимальный балл ${index + 1}`}
                className="rounded-lg border border-line px-3 py-2 text-sm"
                type="number"
                min={0}
                value={criterion.max_score}
                onChange={(event) =>
                  setCriteria((items) =>
                    items.map((item, itemIndex) =>
                      itemIndex === index ? { ...item, max_score: Number(event.target.value) } : item,
                    ),
                  )
                }
              />
            </div>
          ))}
        </div>
        <textarea
          className="mt-3 min-h-36 w-full rounded-xl border border-line p-3 text-sm leading-6"
          value={guide}
          onChange={(event) => setGuide(event.target.value)}
        />
        <div className="mt-3 flex flex-wrap gap-2">
          <button className="button-primary" disabled={!assignment || update.isPending} onClick={() => update.mutate()}>
            Сохранить инструкцию
          </button>
          <button className="button-secondary" disabled={!assignment || reminder.isPending} onClick={() => reminder.mutate()}>
            Напомнить в Telegram
          </button>
        </div>
        {reminder.isSuccess && <p className="mt-3 text-xs text-emerald-700">Уведомление поставлено в очередь.</p>}
        {reminder.error && <p className="mt-3 text-xs text-red-600">{reminder.error.message}</p>}
      </section>
    </div>
  );
}


function Workspace({ role, onLogout }: { role: Role; onLogout: () => void }) {
  const [selectedCourseId, setSelectedCourseId] = useState<number>();
  const [selectedAssignmentId, setSelectedAssignmentId] = useState<number>();
  const [selectedSubmissionId, setSelectedSubmissionId] = useState<number>();

  const courses = useQuery({ queryKey: ["courses"], queryFn: () => api<Course[]>("/api/courses") });
  const courseId = selectedCourseId ?? courses.data?.[0]?.id;

  const assignments = useQuery({
    queryKey: ["assignments", courseId],
    queryFn: () => api<AssignmentListItem[]>(`/api/courses/${courseId}/assignments`),
    enabled: Boolean(courseId),
  });
  const assignmentId = selectedAssignmentId ?? assignments.data?.[0]?.id;

  const assignment = useQuery({
    queryKey: ["assignment", assignmentId],
    queryFn: () => api<Assignment>(`/api/assignments/${assignmentId}`),
    enabled: Boolean(assignmentId),
  });
  const submissionId = selectedSubmissionId ?? assignment.data?.submissions[0]?.id;

  if (courses.error) {
    return (
      <main className="grid min-h-screen place-items-center p-6 text-center">
        <div><h1 className="text-2xl font-semibold">Backend недоступен</h1><p className="mt-2 text-slate-500">{courses.error.message}</p></div>
      </main>
    );
  }

  const currentSubmission = assignment.data?.submissions.find((item) => item.id === submissionId);
  const progress = assignment.data?.submissions.length
    ? Math.round((assignment.data.submissions.filter((item) => item.status === "reviewed").length / assignment.data.submissions.length) * 100)
    : 0;

  return (
    <main className="grid min-h-screen lg:grid-cols-[260px_1fr]">
      <Sidebar
        role={role}
        courses={courses.data ?? []}
        selectedCourse={courseId}
        onCourse={(id) => {
          setSelectedCourseId(id);
          setSelectedAssignmentId(undefined);
          setSelectedSubmissionId(undefined);
        }}
        onLogout={onLogout}
      />
      <div className="min-w-0 p-4 md:p-8">
        <header className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <p className="label">{role === "reviewer" ? "Рабочее место ревьюера" : "Контроль потока"}</p>
            <h1 className="text-3xl font-semibold">{assignment.data?.title ?? "Загрузка задания…"}</h1>
            {assignment.data && (
              <p className="mt-2 text-sm text-slate-500">
                Дедлайн: {new Date(assignment.data.deadline).toLocaleString("ru-RU")}
              </p>
            )}
          </div>
          {assignment.data && (
            <a className="button-secondary" href={assignment.data.task_url} target="_blank">Открыть условие</a>
          )}
        </header>

        <div className="mt-6 flex gap-2 overflow-x-auto pb-1">
          {assignments.data?.map((item) => (
            <button
              key={item.id}
              className={assignmentId === item.id ? "button-primary whitespace-nowrap" : "button-secondary whitespace-nowrap"}
              onClick={() => {
                setSelectedAssignmentId(item.id);
                setSelectedSubmissionId(undefined);
              }}
            >
              {item.title} · {item.reviewed}/{item.total}
            </button>
          ))}
        </div>

        <div className="mt-6 panel p-4">
          <div className="flex items-center justify-between text-sm">
            <span className="font-semibold">Прогресс проверки</span><span>{progress}%</span>
          </div>
          <div className="mt-2 h-2 overflow-hidden rounded-full bg-stone-100">
            <div className="h-full rounded-full bg-brand transition-all" style={{ width: `${progress}%` }} />
          </div>
        </div>

        <div className="mt-6">
          {role === "methodist" ? (
            <MethodistDashboard key={assignment.data?.id ?? "loading"} assignment={assignment.data} />
          ) : (
            <div className="grid gap-5 xl:grid-cols-[1.45fr_0.75fr]">
              <section className="panel overflow-hidden">
                <div className="flex items-center justify-between p-5">
                  <div><p className="label">Очередь</p><h2 className="text-xl font-semibold">Работы студентов</h2></div>
                  <span className="text-sm text-slate-500">{assignment.data?.submissions.length ?? 0} работ</span>
                </div>
                {assignment.data && (
                  <SubmissionTable
                    submissions={assignment.data.submissions}
                    selectedId={submissionId}
                    onSelect={(item) => setSelectedSubmissionId(item.id)}
                  />
                )}
              </section>
              {currentSubmission && (
                <ReviewPanel
                  key={currentSubmission.id}
                  submission={currentSubmission}
                  assignmentId={assignment.data!.id}
                  onNext={(item) => setSelectedSubmissionId(item.id)}
                />
              )}
            </div>
          )}
        </div>
      </div>
    </main>
  );
}


export default function Home() {
  const [role, setRole] = useState<Role | null>(null);
  return role ? <Workspace role={role} onLogout={() => setRole(null)} /> : <Login onLogin={setRole} />;
}
