"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import { FormEvent, useEffect, useRef, useState } from "react";

import { homeworkApi } from "@/lib/api";
import { activityLogger } from "@/lib/logger";
import type { Assignment, Criterion, HomeworkListItem, Submission } from "@/lib/types";
import { Modal, ProgressBar, ResourceLinks } from "@/components/ui";


export function ReviewerHomework({
  assignment,
  listItem,
  onRefresh,
}: {
  assignment: Assignment;
  listItem: HomeworkListItem;
  onRefresh: () => Promise<unknown>;
}) {
  const [clarification, setClarification] = useState("");
  const [showClarification, setShowClarification] = useState(false);
  const [current, setCurrent] = useState<Submission | null>(null);
  const pollAttempts = useRef(0);
  const [pollTimedOut, setPollTimedOut] = useState(false);
  useEffect(() => {
    pollAttempts.current = 0;
    setPollTimedOut(false);
  }, [current?.id]);
  const evaluation = useQuery({
    queryKey: ["submission-evaluation", current?.id],
    queryFn: () => homeworkApi.getSubmission(current!.id),
    enabled: current !== null,
    refetchInterval: (query) => {
      const status = query.state.data?.evaluation_status;
      if (status !== "queued" && status !== "processing") return false;
      pollAttempts.current += 1;
      if (pollAttempts.current >= 30) {
        setPollTimedOut(true);
        return false;
      }
      return 2000;
    },
  });
  const activeSubmission = evaluation.data ?? current;

  const checked = assignment.submissions.filter(
    (item) => item.status === "reviewed",
  );
  const assignedTotal = listItem.reviewer_total ?? assignment.submissions.length;
  const assignedChecked = listItem.reviewer_checked ?? checked.length;

  const clarify = useMutation({
    mutationFn: () => homeworkApi.clarify(assignment.id, clarification),
    onSuccess: () => {
      setClarification("");
      setShowClarification(false);
    },
  });
  const getNext = useMutation({
    mutationFn: async () => {
      const submission = await homeworkApi.next(assignment.id);
      activityLogger.info("reviewer.next_submission", { assignmentId: assignment.id, submissionId: submission.id });
      return homeworkApi.createDraft(submission.id);
    },
    onSuccess: (submission) => {
      setCurrent(submission);
      onRefresh();
    },
  });

  return (
    <div className="space-y-5">
      <section className="card p-5">
        <div className="flex flex-wrap items-center gap-3">
          <ResourceLinks taskUrl={assignment.task_url} criteriaUrl={assignment.criteria_url} />
          <button
            onClick={() => setShowClarification((value) => !value)}
            className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-1.5 text-xs font-medium text-warning transition hover:bg-amber-100"
          >
            Уточнить условие / критерии
          </button>
        </div>
        {showClarification && (
          <div className="mt-4 border-t border-border pt-4">
            <p className="mb-2 text-xs text-muted">Вопрос или предложение сразу попадёт методисту.</p>
            <textarea
              value={clarification}
              onChange={(event) => setClarification(event.target.value)}
              placeholder="Опишите, что нужно уточнить…"
              rows={3}
            />
            <div className="mt-3 flex items-center gap-3">
              <button
                className="button-warning"
                disabled={clarification.trim().length < 5 || clarify.isPending}
                onClick={() => clarify.mutate()}
              >
                Отправить методисту
              </button>
              {clarify.error && <span className="text-xs text-danger">{clarify.error.message}</span>}
            </div>
          </div>
        )}
      </section>

      {assignment.criteria.length > 0 && (
        <section className="card p-5">
          <h2 className="mb-3 text-sm font-semibold">Критерии оценки</h2>
          <ul className="space-y-3">
            {assignment.criteria.map((criterion) => (
              <li key={criterion.title} className="rounded-lg border border-border bg-secondary p-3">
                <div className="flex items-start justify-between gap-3">
                  <p className="text-sm font-medium">{criterion.title}</p>
                  <span className="font-mono text-xs text-muted">{criterion.max_score} б.</span>
                </div>
                {criterion.description?.trim() ? (
                  <p className="mt-1 text-xs leading-5 text-muted">{criterion.description}</p>
                ) : null}
              </li>
            ))}
          </ul>
        </section>
      )}

      {assignment.reviewer_guide.trim() && (
        <section className="card border-l-4 border-l-accent p-5">
          <p className="eyebrow">Для ревьюера</p>
          <h2 className="mb-2 text-sm font-semibold">Пособие по проверке</h2>
          <p className="whitespace-pre-wrap text-sm leading-6 text-slate-700">
            {assignment.reviewer_guide}
          </p>
        </section>
      )}

      <section className="card p-5">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-sm font-semibold">Мой прогресс</h2>
          <span className="font-mono text-xs text-muted">{assignedChecked} / {assignedTotal}</span>
        </div>
        <ProgressBar
          value={assignedChecked}
          total={assignedTotal}
          tone={assignedChecked === assignedTotal ? "success" : "accent"}
        />
      </section>

      <section className="card overflow-hidden">
        <div className="flex items-center justify-between border-b border-border px-5 py-4">
          <h2 className="text-sm font-semibold">Проверенные студенты</h2>
          <span className="font-mono text-xs text-muted">{checked.length} записей</span>
        </div>
        <div className="max-h-72 overflow-auto">
          <table className="w-full min-w-[680px] text-xs">
            <thead className="sticky top-0 bg-slate-50 text-left uppercase tracking-wide text-muted">
              <tr>
                <th className="px-5 py-3 font-medium">Студент</th>
                <th className="px-4 py-3 font-medium">Stepik</th>
                <th className="px-4 py-3 font-medium">Работа</th>
                <th className="px-4 py-3 text-center font-medium">Балл</th>
                <th className="px-4 py-3 text-center font-medium">Нарушение</th>
                <th className="px-4 py-3" />
              </tr>
            </thead>
            <tbody className="divide-y divide-secondary">
              {checked.map((student) => (
                <tr key={student.id} className="transition hover:bg-slate-50">
                  <td className="px-5 py-3 font-medium">{student.student_name}</td>
                  <td className="px-4 py-3"><ExternalTextLink href={student.stepik_url}>Stepik</ExternalTextLink></td>
                  <td className="px-4 py-3"><ExternalTextLink href={student.work_url}>Работа</ExternalTextLink></td>
                  <td className="px-4 py-3 text-center font-mono font-semibold">{student.score ?? "—"}</td>
                  <td className="px-4 py-3 text-center">
                    <span className={`rounded-md px-2 py-0.5 ${student.integrity_flag ? "bg-red-50 text-danger" : "bg-emerald-50 text-success"}`}>
                      {student.integrity_flag ? "Есть сигнал" : "Нет"}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-right">
                    <button
                      className="font-medium text-accent hover:underline"
                      onClick={() => {
                        void homeworkApi.getSubmission(student.id).then(setCurrent);
                      }}
                    >
                      Редактировать
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {!checked.length && <div className="py-10 text-center text-xs text-muted">Проверок пока нет</div>}
        </div>
      </section>

      {!current && (
        <section className="card flex flex-wrap items-center justify-between gap-4 p-5">
          <div>
            <h2 className="text-sm font-semibold">Следующая работа</h2>
            <p className="mt-1 text-xs text-muted">
              Осталось {Math.max(0, assignedTotal - assignedChecked)} из назначенных вам работ
            </p>
          </div>
          <button
            className="button-primary"
            disabled={getNext.isPending}
            onClick={() => {
              activityLogger.info("reviewer.next_clicked", { assignmentId: assignment.id });
              getNext.mutate();
            }}
          >
            {getNext.isPending ? "AI анализирует работу…" : "Получить следующего →"}
          </button>
          {getNext.error && <p className="w-full text-xs text-danger">{getNext.error.message}</p>}
        </section>
      )}
      {activeSubmission && (
        <Modal
          title={`Проверка: ${activeSubmission.student_name}`}
          onClose={() => setCurrent(null)}
        >
          <ReviewEditor
            key={`${activeSubmission.id}-${activeSubmission.evaluation_status}-${activeSubmission.latest_evaluation_id ?? "edit"}`}
            submission={activeSubmission}
            criteria={assignment.criteria}
            pollTimedOut={pollTimedOut}
            onCancel={() => setCurrent(null)}
            onSaved={async () => {
              setCurrent(null);
              await onRefresh();
            }}
          />
        </Modal>
      )}
    </div>
  );
}


function ReviewEditor({
  submission,
  criteria,
  pollTimedOut,
  onCancel,
  onSaved,
}: {
  submission: Submission;
  criteria: Criterion[];
  pollTimedOut: boolean;
  onCancel: () => void;
  onSaved: () => Promise<void>;
}) {
  const structuredScores = submission.review_json?.criterion_results ?? [];
  const [summary, setSummary] = useState(
    submission.summary ?? submission.ai_draft?.summary ?? submission.review_json?.summary_feedback ?? "",
  );
  const [integrity, setIntegrity] = useState(submission.integrity_flag ?? "");
  const [scores, setScores] = useState(() =>
    criteria.map((criterion, index) => {
      const saved = submission.criterion_scores?.find(
        (item) => item.criterion_index === index,
      );
      const draft = submission.ai_draft?.scores.find(
        (item) => item.criterion === criterion.title,
      );
      const structured = structuredScores.find(
        (item) => item.criterion_name === criterion.title,
      );
      return {
        criterion_index: index,
        score: saved?.score ?? draft?.score ?? structured?.assigned_score ?? 0,
        comment: saved?.comment ?? draft?.comment ?? structured?.reasoning ?? "",
      };
    }),
  );
  const totalScore = scores.reduce((sum, item) => sum + item.score, 0);
  const save = useMutation({
    mutationFn: () =>
      homeworkApi.saveReview(submission.id, {
        criterion_scores: scores,
        summary,
        integrity_flag: integrity.trim() || null,
      }),
    onSuccess: async () => {
      activityLogger.info("reviewer.review_saved", { submissionId: submission.id });
      await onSaved();
    },
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    save.mutate();
  }

  return (
    <section className="overflow-hidden rounded-xl border border-accent bg-white shadow-lg">
      <div className="bg-gradient-to-r from-primary to-accent px-5 py-5 text-white">
        <p className="text-xs font-semibold uppercase tracking-wider text-white/70">AI-отчёт · автоматический анализ</p>
        <h2 className="mt-1 font-display text-2xl">{submission.student_name}</h2>
        <div className="mt-2 flex gap-4 text-xs">
          <a href={submission.stepik_url} target="_blank" rel="noreferrer" className="underline">Stepik ↗</a>
          <a href={submission.work_url} target="_blank" rel="noreferrer" className="underline">Открыть работу ↗</a>
        </div>
      </div>

      <form className="space-y-5 p-5" onSubmit={submit}>
        <div className="rounded-lg border border-border bg-secondary p-4">
          <p className="eyebrow">Текстовый отчёт</p>
          <p className="text-sm leading-6 text-slate-700">
            {submission.ai_draft?.summary ?? submission.review_json?.summary_feedback ?? submission.summary ?? "Сохранённая проверка доступна для редактирования."}
          </p>
          {submission.ai_draft?.scores || structuredScores.length > 0 ? (
            <div className="mt-4 grid gap-2">
              {(submission.ai_draft?.scores ?? structuredScores.map((item) => ({
                criterion: item.criterion_name,
                score: item.assigned_score,
                max_score: item.max_points,
                comment: item.reasoning,
                evidence: item.evidence,
              }))).map((item) => (
                <div key={item.criterion} className="flex gap-3 rounded-lg bg-white p-3 text-xs">
                  <span className="min-w-0 flex-1">
                    <strong>{item.criterion}</strong>
                    <span className="mt-1 block text-muted">{item.comment}</span>
                  </span>
                  <span className="shrink-0 font-mono font-semibold">{item.score}/{item.max_score}</span>
                </div>
              ))}
            </div>
          ) : null}
        </div>

        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
          <Metric label="Оценка AI" value={`${submission.ai_draft?.total ?? submission.review_json?.total_score ?? "—"}/100`} />
          <Metric label="Критериев" value={String(submission.ai_draft?.scores.length ?? structuredScores.length ?? "—")} />
          <Metric
            label="AI-сигнал"
            value={submission.ai_assessment_json ? `${Math.round(submission.ai_assessment_json.confidence * 100)}%` : submission.ai_draft ? `${Math.round(submission.ai_draft.integrity.confidence * 100)}%` : "—"}
          />
        </div>

        {pollTimedOut && submission.evaluation_status !== "completed" && submission.evaluation_status !== "failed" && (
          <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-danger">Не удалось дождаться результата AI-проверки за 60 секунд.</div>
        )}
        {submission.evaluation_status && submission.evaluation_status !== "completed" && (
          <div className={`rounded-lg border p-3 text-sm ${submission.evaluation_status === "failed" ? "border-red-200 bg-red-50 text-danger" : "border-amber-200 bg-amber-50 text-warning"}`}>
            {submission.evaluation_status === "failed" ? `AI-проверка завершилась ошибкой: ${submission.evaluation_error ?? "неизвестная ошибка"}` : "AI-проверка выполняется. Результаты появятся автоматически."}
          </div>
        )}

        <label className="block">
          <span className="field-label">Краткий итог проверки</span>
          <textarea rows={4} value={summary} onChange={(event) => setSummary(event.target.value)} required />
        </label>
        <label className="block">
          <span className="field-label">Нарушение самостоятельности</span>
          <textarea
            rows={2}
            value={integrity}
            onChange={(event) => setIntegrity(event.target.value)}
            placeholder={submission.ai_draft?.integrity.reason ?? "Оставьте пустым, если нарушений нет"}
          />
        </label>
        <section>
          <div className="mb-3 flex items-center justify-between gap-3">
            <div>
              <p className="eyebrow">Финальное решение</p>
              <h3 className="text-sm font-semibold">Оценки по критериям</h3>
            </div>
            <span className="font-mono text-lg font-semibold">{totalScore}/100</span>
          </div>
          <div className="space-y-3">
            {criteria.map((criterion, index) => (
              <div key={`${index}-${criterion.title}`} className="rounded-lg border border-border p-3">
                <div className="grid grid-cols-[1fr_100px] items-start gap-3">
                  <div>
                    <p className="text-sm font-medium">{criterion.title}</p>
                    {criterion.description?.trim() ? (
                      <p className="mt-1 text-xs leading-5 text-muted">{criterion.description}</p>
                    ) : null}
                  </div>
                  <label>
                    <span className="field-label">Балл из {criterion.max_score}</span>
                    <input
                      type="number"
                      min={0}
                      max={criterion.max_score}
                      value={scores[index].score}
                      onChange={(event) =>
                        setScores((current) =>
                          current.map((item, itemIndex) =>
                            itemIndex === index
                              ? { ...item, score: Number(event.target.value) }
                              : item,
                          ),
                        )
                      }
                    />
                  </label>
                </div>
                <textarea
                  className="mt-2"
                  rows={2}
                  value={scores[index].comment}
                  placeholder="Комментарий по критерию"
                  onChange={(event) =>
                    setScores((current) =>
                      current.map((item, itemIndex) =>
                        itemIndex === index
                          ? { ...item, comment: event.target.value }
                          : item,
                      ),
                    )
                  }
                />
              </div>
            ))}
          </div>
        </section>

        {save.error && <p className="text-xs text-danger">{save.error.message}</p>}
        <div className="flex flex-wrap gap-3 border-t border-border pt-4">
          <button className="button-success" disabled={save.isPending || submission.evaluation_status === "queued" || submission.evaluation_status === "processing"}>Закончить проверку</button>
          {(submission.status === "reviewed" || submission.evaluation_status === "completed") && (
            <button
              type="button"
              className="button-secondary"
              onClick={() => {
                activityLogger.info("reviewer.download_report_clicked", { submissionId: submission.id });
                void homeworkApi.downloadReport(submission.id);
              }}
            >
              Скачать PDF
            </button>
          )}
          <button type="button" className="button-secondary" onClick={onCancel}>Отмена</button>
        </div>
      </form>
    </section>
  );
}


function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-border bg-white p-3 text-center">
      <p className="font-mono text-lg font-semibold">{value}</p>
      <p className="mt-0.5 text-[10px] text-muted">{label}</p>
    </div>
  );
}


function ExternalTextLink({ href, children }: { href: string; children: React.ReactNode }) {
  return <a href={href} target="_blank" rel="noreferrer" className="text-accent hover:underline">{children} ↗</a>;
}
