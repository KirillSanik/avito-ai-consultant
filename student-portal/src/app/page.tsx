"use client";

import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { Empty, ErrorMessage, Header, Loader, Logo } from "@/components/ui";
import {
  loadSession,
  saveSession,
  studentAuthApi,
  studentCourseApi,
  studentHomeworkApi,
} from "@/lib/api";
import type {
  AuthResponse,
  StudentCourse,
  StudentUser,
} from "@/lib/types";


type Screen = "auth" | "courses" | "course" | "homework";


export default function Home() {
  const [session, setSession] = useState<AuthResponse | null>(null);
  const [screen, setScreen] = useState<Screen>("auth");
  const [courseId, setCourseId] = useState<number | null>(null);
  const [assignmentId, setAssignmentId] = useState<number | null>(null);
  const [restoring, setRestoring] = useState(true);

  useEffect(() => {
    let cancelled = false;
    async function restore() {
      const stored = loadSession();
      if (!stored) {
        if (!cancelled) setRestoring(false);
        return;
      }
      try {
        const user = await studentAuthApi.me();
        if (cancelled) return;
        const restored = { token: stored.token, user };
        saveSession(restored);
        setSession(restored);
        setScreen("courses");
      } catch {
        saveSession(null);
      } finally {
        if (!cancelled) setRestoring(false);
      }
    }
    void restore();
    return () => {
      cancelled = true;
    };
  }, []);

  function authenticate(auth: AuthResponse) {
    saveSession(auth);
    setSession(auth);
    setScreen("courses");
  }

  function logout() {
    saveSession(null);
    setSession(null);
    setCourseId(null);
    setAssignmentId(null);
    setScreen("auth");
  }

  if (restoring) return <Loader label="Проверяем студенческую сессию…" />;
  if (!session || screen === "auth") {
    return <AuthScreen onAuthenticated={authenticate} />;
  }
  if (screen === "courses") {
    return (
      <CoursesScreen
        user={session.user}
        onLogout={logout}
        onSelect={(id) => {
          setCourseId(id);
          setScreen("course");
        }}
      />
    );
  }
  if (screen === "course" && courseId !== null) {
    return (
      <CourseScreen
        courseId={courseId}
        onLogout={logout}
        onBack={() => setScreen("courses")}
        onSelectHomework={(id) => {
          setAssignmentId(id);
          setScreen("homework");
        }}
      />
    );
  }
  if (screen === "homework" && assignmentId !== null) {
    return (
      <HomeworkScreen
        assignmentId={assignmentId}
        onLogout={logout}
        onBack={() => setScreen("course")}
      />
    );
  }
  return null;
}


function AuthScreen({
  onAuthenticated,
}: {
  onAuthenticated: (auth: AuthResponse) => void;
}) {
  const [mode, setMode] = useState<"login" | "register">("login");
  const [form, setForm] = useState({
    login: "",
    password: "",
    first_name: "",
    last_name: "",
    telegram: "",
  });
  const auth = useMutation({
    mutationFn: () =>
      mode === "login"
        ? studentAuthApi.login(form.login, form.password)
        : studentAuthApi.register(form),
    onSuccess: onAuthenticated,
  });

  return (
    <main className="grid min-h-screen place-items-center px-4 py-8">
      <div className="w-full max-w-md">
        <div className="mb-7 flex justify-center"><Logo /></div>
        <section className="card p-7">
          <p className="eyebrow">Студенческий портал</p>
          <h1 className="mb-6 font-display text-3xl">
            {mode === "login" ? "Войти" : "Создать аккаунт"}
          </h1>
          <form
            className="space-y-4"
            onSubmit={(event) => {
              event.preventDefault();
              auth.mutate();
            }}
          >
            {mode === "register" && (
              <div className="grid grid-cols-2 gap-3">
                <Field label="Имя">
                  <input
                    required
                    value={form.first_name}
                    onChange={(event) =>
                      setForm((current) => ({ ...current, first_name: event.target.value }))
                    }
                  />
                </Field>
                <Field label="Фамилия">
                  <input
                    required
                    value={form.last_name}
                    onChange={(event) =>
                      setForm((current) => ({ ...current, last_name: event.target.value }))
                    }
                  />
                </Field>
              </div>
            )}
            <Field label="Логин">
              <input
                required
                minLength={3}
                autoComplete="username"
                value={form.login}
                onChange={(event) =>
                  setForm((current) => ({ ...current, login: event.target.value }))
                }
              />
            </Field>
            <Field label="Пароль">
              <input
                required
                minLength={4}
                type="password"
                autoComplete={mode === "login" ? "current-password" : "new-password"}
                value={form.password}
                onChange={(event) =>
                  setForm((current) => ({ ...current, password: event.target.value }))
                }
              />
            </Field>
            {mode === "register" && (
              <Field label="Telegram (необязательно)">
                <input
                  value={form.telegram}
                  placeholder="@username"
                  onChange={(event) =>
                    setForm((current) => ({
                      ...current,
                      telegram: event.target.value.replace(/^@/, ""),
                    }))
                  }
                />
              </Field>
            )}
            {auth.error && <ErrorMessage error={auth.error} />}
            <button className="button-primary w-full" disabled={auth.isPending}>
              {auth.isPending
                ? "Подождите…"
                : mode === "login"
                  ? "Войти"
                  : "Зарегистрироваться"}
            </button>
          </form>
          <div className="mt-5 border-t border-border pt-4 text-center text-sm text-muted">
            <button
              className="font-medium text-accent hover:underline"
              onClick={() => {
                setMode(mode === "login" ? "register" : "login");
                auth.reset();
              }}
            >
              {mode === "login" ? "Создать аккаунт студента" : "Уже есть аккаунт"}
            </button>
          </div>
        </section>
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


function CoursesScreen({
  user,
  onSelect,
  onLogout,
}: {
  user: StudentUser;
  onSelect: (id: number) => void;
  onLogout: () => void;
}) {
  const [mine, setMine] = useState(false);
  const courses = useQuery({
    queryKey: ["student-courses", mine],
    queryFn: mine ? studentCourseApi.mine : studentCourseApi.list,
  });

  return (
    <div className="min-h-screen">
      <Header onLogout={onLogout}>
        <span className="hidden text-xs text-muted sm:inline">
          {user.first_name} {user.last_name}
        </span>
      </Header>
      <main className="mx-auto max-w-6xl px-5 py-8">
        <div className="mb-7 flex flex-wrap items-end justify-between gap-4">
          <div>
            <p className="eyebrow">Обучение</p>
            <h1 className="font-display text-4xl">Курсы</h1>
          </div>
          <div className="flex rounded-lg border border-border bg-secondary p-0.5">
            <button
              className={`rounded-md px-4 py-1.5 text-xs font-medium ${
                !mine ? "bg-white ring-1 ring-border" : "text-muted"
              }`}
              onClick={() => setMine(false)}
            >
              Все курсы
            </button>
            <button
              className={`rounded-md px-4 py-1.5 text-xs font-medium ${
                mine ? "bg-white ring-1 ring-border" : "text-muted"
              }`}
              onClick={() => setMine(true)}
            >
              Мои курсы
            </button>
          </div>
        </div>
        {courses.isLoading ? (
          <Loader />
        ) : courses.error ? (
          <ErrorMessage error={courses.error} retry={() => courses.refetch()} />
        ) : !courses.data?.length ? (
          <Empty>{mine ? "Вы пока не зачислены ни на один курс" : "Активных курсов нет"}</Empty>
        ) : (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {courses.data.map((course) => (
              <CourseCard key={course.id} course={course} onClick={() => onSelect(course.id)} />
            ))}
          </div>
        )}
      </main>
    </div>
  );
}


function CourseCard({ course, onClick }: { course: StudentCourse; onClick: () => void }) {
  const statusLabel = {
    none: "Доступен",
    pending: "Заявка отправлена",
    enrolled: "Мой курс",
    rejected: "Заявка отклонена",
  }[course.enrollment_status];
  return (
    <button
      className="card overflow-hidden text-left transition hover:-translate-y-0.5 hover:border-accent hover:shadow-md"
      onClick={onClick}
    >
      <div
        className="flex aspect-[1.9] items-end justify-between p-4 text-white"
        style={{
          background: `linear-gradient(135deg, ${course.cover_color}, ${course.cover_color}99)`,
        }}
      >
        <span className="rounded-full bg-white/20 px-2 py-1 text-[10px]">
          {statusLabel}
        </span>
        <span className="font-mono text-xs">
          {course.enrolled_count} / {course.capacity} мест
        </span>
      </div>
      <div className="p-4">
        <h2 className="text-sm font-semibold">{course.title}</h2>
        <p className="mt-2 line-clamp-2 text-xs leading-5 text-muted">
          {course.description || "Описание появится позже"}
        </p>
      </div>
    </button>
  );
}


function CourseScreen({
  courseId,
  onBack,
  onSelectHomework,
  onLogout,
}: {
  courseId: number;
  onBack: () => void;
  onSelectHomework: (id: number) => void;
  onLogout: () => void;
}) {
  const queryClient = useQueryClient();
  const course = useQuery({
    queryKey: ["student-course", courseId],
    queryFn: () => studentCourseApi.get(courseId),
  });
  const apply = useMutation({
    mutationFn: () => studentCourseApi.apply(courseId),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["student-course", courseId] }),
        queryClient.invalidateQueries({ queryKey: ["student-courses"] }),
      ]);
    },
  });

  return (
    <div className="min-h-screen">
      <Header onLogout={onLogout} />
      <main className="mx-auto max-w-5xl px-5 py-8">
        <button className="mb-5 text-sm text-muted hover:text-foreground" onClick={onBack}>
          ← Все курсы
        </button>
        {course.isLoading ? (
          <Loader />
        ) : course.error ? (
          <ErrorMessage error={course.error} retry={() => course.refetch()} />
        ) : course.data ? (
          <>
            <section className="card mb-6 overflow-hidden">
              <div
                className="p-7 text-white"
                style={{
                  background: `linear-gradient(135deg, ${course.data.cover_color}, ${course.data.cover_color}99)`,
                }}
              >
                <p className="text-xs text-white/75">
                  Поток {course.data.stream} · {course.data.year}
                </p>
                <h1 className="mt-2 font-display text-4xl">{course.data.title}</h1>
                <p className="mt-4 max-w-2xl text-sm leading-6 text-white/85">
                  {course.data.description || "Описание курса появится позже."}
                </p>
              </div>
              <div className="flex flex-wrap items-center justify-between gap-4 p-5">
                <p className="text-sm text-muted">
                  Занято {course.data.enrolled_count} из {course.data.capacity} мест
                </p>
                {course.data.enrollment_status === "none" && (
                  <button
                    className="button-primary"
                    disabled={apply.isPending || course.data.enrolled_count >= course.data.capacity}
                    onClick={() => apply.mutate()}
                  >
                    {apply.isPending ? "Отправляем…" : "Откликнуться"}
                  </button>
                )}
                {course.data.enrollment_status === "pending" && (
                  <span className="rounded-lg bg-amber-50 px-3 py-2 text-sm text-warning">
                    Заявка на рассмотрении
                  </span>
                )}
                {course.data.enrollment_status === "rejected" && (
                  <button className="button-secondary" onClick={() => apply.mutate()}>
                    Отправить заявку повторно
                  </button>
                )}
                {course.data.enrollment_status === "enrolled" && (
                  <div className="text-right">
                    <p className="text-xs text-muted">Набрано баллов</p>
                    <p className="font-mono text-2xl font-semibold">{course.data.total_points}</p>
                  </div>
                )}
              </div>
            </section>
            {apply.error && <ErrorMessage error={apply.error} />}
            {course.data.enrollment_status === "enrolled" && (
              <section>
                <h2 className="mb-4 font-display text-3xl">Домашние задания</h2>
                {!course.data.assignments.length ? (
                  <Empty>Домашних заданий пока нет</Empty>
                ) : (
                  <div className="space-y-3">
                    {course.data.assignments.map((homework) => (
                      <button
                        key={homework.id}
                        className="card flex w-full items-center gap-4 p-5 text-left transition hover:border-accent"
                        onClick={() => onSelectHomework(homework.id)}
                      >
                        <span className="grid h-10 w-10 place-items-center rounded-lg bg-secondary font-mono text-xs">
                          #{homework.number}
                        </span>
                        <div className="flex-1">
                          <h3 className="text-sm font-semibold">{homework.title}</h3>
                          <p className="mt-1 text-xs text-muted">
                            Дедлайн: {new Date(homework.deadline).toLocaleString("ru-RU")}
                          </p>
                        </div>
                        <span className="text-xs font-medium text-accent">
                          {homework.submission?.status === "reviewed"
                            ? `${homework.submission.score ?? 0} баллов`
                            : homework.submission
                              ? "Отправлено"
                              : "Не отправлено"}
                        </span>
                      </button>
                    ))}
                  </div>
                )}
              </section>
            )}
          </>
        ) : null}
      </main>
    </div>
  );
}


function HomeworkScreen({
  assignmentId,
  onBack,
  onLogout,
}: {
  assignmentId: number;
  onBack: () => void;
  onLogout: () => void;
}) {
  const queryClient = useQueryClient();
  const homework = useQuery({
    queryKey: ["student-homework", assignmentId],
    queryFn: () => studentHomeworkApi.get(assignmentId),
  });
  const [workUrl, setWorkUrl] = useState("");
  const submit = useMutation({
    mutationFn: () => studentHomeworkApi.submit(assignmentId, workUrl),
    onSuccess: async () => {
      setWorkUrl("");
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["student-homework", assignmentId] }),
        queryClient.invalidateQueries({ queryKey: ["student-course"] }),
      ]);
    },
  });

  return (
    <div className="min-h-screen">
      <Header onLogout={onLogout} />
      <main className="mx-auto max-w-4xl px-5 py-8">
        <button className="mb-5 text-sm text-muted hover:text-foreground" onClick={onBack}>
          ← К курсу
        </button>
        {homework.isLoading ? (
          <Loader />
        ) : homework.error ? (
          <ErrorMessage error={homework.error} retry={() => homework.refetch()} />
        ) : homework.data ? (
          <div className="space-y-5">
            <section className="card p-6">
              <p className="eyebrow">Домашнее задание #{homework.data.number}</p>
              <h1 className="font-display text-4xl">{homework.data.title}</h1>
              <p className="mt-2 text-sm text-muted">
                Дедлайн: {new Date(homework.data.deadline).toLocaleString("ru-RU")}
              </p>
              <div className="mt-5 flex gap-3">
                <a
                  className="button-primary"
                  href={homework.data.task_url}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  Открыть условие
                </a>
              </div>
            </section>
            <section className="card p-6">
              <h2 className="text-sm font-semibold">Отправить работу на проверку</h2>
              {homework.data.submission && (
                <div className="my-4 rounded-lg bg-secondary p-3 text-sm">
                  <p>
                    Статус: <b>{homework.data.submission.status}</b>
                    {homework.data.submission.score !== null
                      ? ` · ${homework.data.submission.score} баллов`
                      : ""}
                  </p>
                  <a
                    href={homework.data.submission.work_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="mt-1 block truncate text-xs text-accent hover:underline"
                  >
                    {homework.data.submission.work_url}
                  </a>
                  {homework.data.submission.summary && (
                    <p className="mt-2 text-xs text-muted">
                      {homework.data.submission.summary}
                    </p>
                  )}
                  <p className="mt-3 text-xs text-muted">
                    Работа уже отправлена. Повторная отправка недоступна.
                  </p>
                </div>
              )}
              {!homework.data.submission && (
                <form
                  className="mt-4 flex flex-wrap items-end gap-3"
                  onSubmit={(event) => {
                    event.preventDefault();
                    submit.mutate();
                  }}
                >
                  <label className="min-w-[260px] flex-1">
                    <span className="field-label">Ссылка GitHub или Google Drive</span>
                    <input
                      type="url"
                      required
                      value={workUrl}
                      placeholder="https://github.com/..."
                      onChange={(event) => setWorkUrl(event.target.value)}
                    />
                  </label>
                  <button className="button-primary" disabled={submit.isPending}>
                    {submit.isPending ? "Отправляем…" : "Отправить на проверку"}
                  </button>
                </form>
              )}
              {submit.error && <div className="mt-3"><ErrorMessage error={submit.error} /></div>}
              {submit.isSuccess && (
                <p className="mt-3 text-xs text-success">Работа отправлена</p>
              )}
            </section>
          </div>
        ) : null}
      </main>
    </div>
  );
}
