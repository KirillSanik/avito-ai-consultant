"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { ErrorState, ExternalLink, Modal, ProgressBar, ResourceLinks } from "@/components/ui";
import { XlsxImportCard } from "@/components/xlsx";
import { courseApi, homeworkApi } from "@/lib/api";
import type { Assignment, Submission } from "@/lib/types";


export function MethodistHomework({
  assignment,
  onRefresh,
}: {
  assignment: Assignment;
  onRefresh: () => Promise<unknown>;
}) {
  const queryClient = useQueryClient();
  const [guide, setGuide] = useState(assignment.reviewer_guide);
  const [selectedReviewerId, setSelectedReviewerId] = useState("");
  const [showAddReviewer, setShowAddReviewer] = useState(false);
  const [openedSubmission, setOpenedSubmission] = useState<Submission | null>(null);

  const reviewers = useQuery({
    queryKey: ["reviewers", assignment.id],
    queryFn: () => homeworkApi.reviewers(assignment.id),
  });
  const courseReviewers = useQuery({
    queryKey: ["course-reviewers", assignment.course_id],
    queryFn: () => courseApi.reviewers(assignment.course_id),
  });
  const dashboard = useQuery({ queryKey: ["dashboard"], queryFn: homeworkApi.dashboard });
  const refreshReviewers = () => queryClient.invalidateQueries({ queryKey: ["reviewers", assignment.id] });

  const saveCriteria = useMutation({
    mutationFn: () => homeworkApi.updateCriteria(assignment.id, [], guide),
    onSuccess: () => onRefresh(),
  });
  const addReviewer = useMutation({
    mutationFn: (userId: number) => homeworkApi.addReviewer(assignment.id, userId),
    onSuccess: () => {
      setSelectedReviewerId("");
      setShowAddReviewer(false);
      refreshReviewers();
      onRefresh();
    },
  });
  const addAllReviewers = useMutation({
    mutationFn: () =>
      homeworkApi.addReviewersBulk(
        assignment.id,
        availableCourseReviewers.map((reviewer) => Number(reviewer.user_id)),
      ),
    onSuccess: () => {
      refreshReviewers();
      onRefresh();
    },
  });
  const removeReviewer = useMutation({
    mutationFn: (reviewerId: number) => homeworkApi.removeReviewer(assignment.id, reviewerId),
    onSuccess: () => {
      refreshReviewers();
      onRefresh();
    },
  });
  const updateSuggestion = useMutation({
    mutationFn: (id: number) => homeworkApi.updateClarification(id, "dismissed"),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["dashboard"] }),
  });

  const assignedUserIds = new Set((reviewers.data ?? []).map((item) => String(item.user_id)));
  const availableCourseReviewers = (courseReviewers.data ?? []).filter(
    (item) => !assignedUserIds.has(String(item.user_id)),
  );
  const reviewed = assignment.submissions.filter((item) => item.status === "reviewed").length;
  const total = assignment.submissions.length;
  const progress = total > 0 ? Math.round((reviewed / total) * 100) : 0;
  const suggestions = (dashboard.data?.clarifications ?? []).filter(
    (item) => item.assignment_id === assignment.id && item.status === "open",
  );

  return (
    <div className="space-y-5">
      <section className="card p-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <ResourceLinks taskUrl={assignment.task_url} criteriaUrl={assignment.criteria_url} />
        </div>
      </section>

      <section className="card p-5">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-sm font-semibold">Глобальный прогресс проверки</h2>
          <span className="font-mono text-xs text-muted">{reviewed} / {total}</span>
        </div>
        <ProgressBar
          value={reviewed}
          total={total}
          tone={progress >= 80 ? "success" : progress >= 40 ? "warning" : "danger"}
        />
        <div className="mt-4 grid grid-cols-3 gap-3">
          <Metric label="Всего студентов" value={total} />
          <Metric label="Проверено" value={reviewed} />
          <Metric label="Осталось" value={total - reviewed} />
        </div>
      </section>

      <section className="card overflow-hidden">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border px-5 py-4">
          <h2 className="text-sm font-semibold">Прогресс ревьюеров</h2>
          {!showAddReviewer ? (
            <div className="flex flex-wrap gap-3">
              <button
                type="button"
                className="text-xs font-medium text-accent hover:underline"
                disabled={!availableCourseReviewers.length || addAllReviewers.isPending}
                onClick={() => addAllReviewers.mutate()}
              >
                {addAllReviewers.isPending ? "Добавляем…" : "Добавить всех с курса"}
              </button>
              <button className="text-xs font-medium text-accent hover:underline" onClick={() => setShowAddReviewer(true)}>
                + Назначить ревьюера
              </button>
            </div>
          ) : (
            <div className="flex flex-wrap items-center gap-2">
              <select
                className="min-w-[220px] py-1.5 text-xs"
                value={selectedReviewerId}
                onChange={(event) => setSelectedReviewerId(event.target.value)}
                disabled={courseReviewers.isLoading || !availableCourseReviewers.length}
              >
                <option value="">
                  {courseReviewers.isLoading
                    ? "Загружаем…"
                    : availableCourseReviewers.length
                      ? "Ревьюер курса"
                      : "Все ревьюеры курса уже назначены"}
                </option>
                {availableCourseReviewers.map((reviewer) => (
                  <option key={reviewer.user_id} value={reviewer.user_id}>
                    {reviewer.first_name} {reviewer.last_name}
                  </option>
                ))}
              </select>
              <button
                type="button"
                className="button-primary py-1.5 text-xs"
                disabled={!selectedReviewerId || addReviewer.isPending}
                onClick={() => addReviewer.mutate(Number(selectedReviewerId))}
              >
                Добавить
              </button>
              <button type="button" className="text-xs text-muted" onClick={() => setShowAddReviewer(false)}>Отмена</button>
            </div>
          )}
        </div>
        {addReviewer.error && (
          <p className="border-b border-red-100 bg-red-50 px-5 py-2 text-xs text-danger">
            {addReviewer.error.message}
          </p>
        )}
        {addAllReviewers.error && (
          <p className="border-b border-red-100 bg-red-50 px-5 py-2 text-xs text-danger">
            {addAllReviewers.error.message}
          </p>
        )}
        {reviewers.error ? (
          <div className="p-5"><ErrorState message={reviewers.error.message} onRetry={() => reviewers.refetch()} /></div>
        ) : (
          <div className="divide-y divide-secondary">
            {(reviewers.data ?? []).map((reviewer) => {
              const percent = reviewer.total > 0 ? Math.round((reviewer.checked / reviewer.total) * 100) : 0;
              return (
                <div key={reviewer.id} className="flex items-center gap-4 px-5 py-4">
                  <div className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-indigo-50 text-xs font-semibold text-accent">
                    {reviewerInitial(reviewer)}
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="mb-2 flex flex-wrap items-center gap-2">
                      <span className="truncate text-sm font-medium">{reviewerDisplayName(reviewer)}</span>
                      <span className="text-xs text-muted">@{reviewer.telegram}</span>
                      {reviewer.anomaly && (
                        <span className="rounded-md border border-red-200 bg-red-50 px-2 py-0.5 text-[10px] font-medium text-danger">
                          Аномалия
                        </span>
                      )}
                    </div>
                    <ProgressBar
                      value={reviewer.checked}
                      total={reviewer.total}
                      tone={reviewer.anomaly ? "danger" : percent === 100 ? "success" : "accent"}
                    />
                  </div>
                  <span className="font-mono text-xs text-muted">{reviewer.checked}/{reviewer.total}</span>
                  <button
                    className="text-lg text-muted hover:text-danger"
                    title="Удалить ревьюера"
                    onClick={() => removeReviewer.mutate(reviewer.id)}
                  >
                    ×
                  </button>
                </div>
              );
            })}
            {!reviewers.isLoading && !reviewers.data?.length && (
              <div className="py-8 text-center text-xs text-muted">Ревьюеры ещё не назначены</div>
            )}
          </div>
        )}
        <div className="border-t border-border p-5">
          <XlsxImportCard
            title="Импорт ревьюеров ДЗ из XLSX"
            hint="Колонка login. Назначить можно только ревьюеров этого курса."
            onPreview={(file) => homeworkApi.importReviewers(assignment.id, file, false)}
            onConfirm={(file) => homeworkApi.importReviewers(assignment.id, file, true)}
            onApplied={async () => {
              refreshReviewers();
              await onRefresh();
            }}
          />
        </div>
      </section>

      <section className="card overflow-hidden">
        <div className="border-b border-border px-5 py-4">
          <h2 className="text-sm font-semibold">Предложения от ревьюеров</h2>
        </div>
        <div className="divide-y divide-secondary">
          {suggestions.map((suggestion) => (
            <div key={suggestion.id} className="flex items-start gap-3 px-5 py-4">
              <div className="grid h-7 w-7 shrink-0 place-items-center rounded-full bg-amber-100 text-xs font-semibold text-warning">
                {suggestion.author[0]}
              </div>
              <div className="min-w-0 flex-1">
                <p className="text-xs font-semibold text-muted">{suggestion.author}</p>
                <p className="mt-1 text-sm leading-6 text-slate-700">{suggestion.message}</p>
              </div>
              <button
                type="button"
                aria-label="Убрать предложение"
                title="Убрать уведомление"
                className="text-lg text-muted hover:text-danger"
                disabled={updateSuggestion.isPending}
                onClick={() => updateSuggestion.mutate(suggestion.id)}
              >
                ×
              </button>
            </div>
          ))}
          {!suggestions.length && <div className="py-8 text-center text-xs text-muted">Новых предложений нет</div>}
        </div>
      </section>

      <section className="card overflow-hidden">
        <div className="border-b border-border px-5 py-4">
          <h2 className="text-sm font-semibold">Пособие для ревьюеров</h2>
        </div>
        <div className="space-y-4 p-5">
          <label className="block">
            <span className="field-label">Пособие для ревьюеров</span>
            <textarea rows={4} value={guide} onChange={(event) => setGuide(event.target.value)} />
          </label>
          <button
            type="button"
            className="button-primary"
            disabled={saveCriteria.isPending}
            onClick={() => saveCriteria.mutate()}
          >
            Сохранить изменения
          </button>
          {saveCriteria.isSuccess && <span className="ml-3 text-xs text-success">Сохранено</span>}
          {saveCriteria.error && <p className="text-xs text-danger">{saveCriteria.error.message}</p>}
        </div>
      </section>

      <section className="card overflow-hidden">
        <div className="border-b border-border px-5 py-4"><h2 className="text-sm font-semibold">Оценки студентов</h2></div>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[620px] text-xs">
            <thead className="bg-slate-50 text-left uppercase tracking-wide text-muted">
              <tr>
                <th className="px-5 py-3 font-medium">Студент</th>
                <th className="px-4 py-3 text-center font-medium">Балл</th>
                <th className="px-4 py-3 text-center font-medium">Нарушение</th>
                <th className="px-4 py-3 font-medium">Ревьюер</th>
                <th className="px-4 py-3 font-medium">Работа</th>
                <th className="px-4 py-3" />
              </tr>
            </thead>
            <tbody className="divide-y divide-secondary">
              {assignment.submissions.map((student) => (
                <tr key={student.id}>
                  <td className="px-5 py-3 font-medium">{student.student_name}</td>
                  <td className="px-4 py-3 text-center font-mono font-semibold">{student.score ?? "—"}</td>
                  <td className="px-4 py-3 text-center">
                    <span className={student.integrity_flag ? "text-danger" : "text-success"}>
                      {student.integrity_flag ? "Есть сигнал" : "Нет"}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-muted">{student.reviewer ?? "Не назначен"}</td>
                  <td className="px-4 py-3"><ExternalLink href={student.work_url}>Открыть</ExternalLink></td>
                  <td className="px-4 py-3 text-right">
                    {student.status === "reviewed" && (
                      <button
                        type="button"
                        className="text-xs font-medium text-accent hover:underline"
                        onClick={() => {
                          void homeworkApi.getSubmission(student.id).then(setOpenedSubmission);
                        }}
                      >
                        Просмотр
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
      {openedSubmission && (
        <Modal
          title={`Проверенная работа: ${openedSubmission.student_name}`}
          onClose={() => setOpenedSubmission(null)}
        >
          <div className="space-y-4">
            <div className="flex flex-wrap gap-3">
              <ExternalLink href={openedSubmission.work_url}>Открыть работу</ExternalLink>
              {openedSubmission.stepik_url && (
                <ExternalLink href={openedSubmission.stepik_url}>Stepik</ExternalLink>
              )}
            </div>
            <div className="rounded-lg bg-secondary p-4">
              <p className="text-xs text-muted">Итоговый балл</p>
              <p className="font-mono text-3xl font-semibold">
                {openedSubmission.score ?? "—"} / 100
              </p>
            </div>
            {(openedSubmission.criterion_scores ?? []).map((criterion) => (
              <div key={criterion.criterion_index} className="rounded-lg border border-border p-3">
                <div className="flex justify-between gap-3">
                  <p className="text-sm font-medium">{criterion.criterion}</p>
                  <span className="font-mono text-xs">
                    {criterion.score}/{criterion.max_score}
                  </span>
                </div>
                {criterion.comment && (
                  <p className="mt-1 text-xs leading-5 text-muted">{criterion.comment}</p>
                )}
              </div>
            ))}
            <div>
              <p className="field-label">Итоговый комментарий</p>
              <p className="whitespace-pre-wrap text-sm leading-6">
                {openedSubmission.summary || "Комментария нет"}
              </p>
            </div>
          </div>
        </Modal>
      )}
    </div>
  );
}


function reviewerDisplayName(reviewer: { name?: string; first_name?: string; login?: string }) {
  return reviewer.name || reviewer.first_name || reviewer.login || "Р";
}


function reviewerInitial(reviewer: { name?: string; first_name?: string; login?: string }) {
  return reviewerDisplayName(reviewer).charAt(0).toUpperCase();
}


function Metric({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-lg border border-border bg-secondary p-3 text-center">
      <p className="font-mono text-xl font-semibold">{value}</p>
      <p className="mt-0.5 text-[10px] text-muted">{label}</p>
    </div>
  );
}
