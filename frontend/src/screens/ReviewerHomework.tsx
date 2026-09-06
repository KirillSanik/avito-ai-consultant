"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import { FormEvent, useState } from "react";

import { homeworkApi } from "@/lib/api";
import { activityLogger } from "@/lib/logger";
import { formatScore, parseScore, sumScores } from "@/lib/scores";
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
  const evaluation = useQuery({
    queryKey: ["submission-evaluation", current?.id],
    queryFn: () => homeworkApi.getSubmission(current!.id),
    enabled: current !== null,
    refetchInterval: (query) => {
      const status = query.state.data?.evaluation_status;
      if (status !== "queued" && status !== "processing") return false;
      return 2000;
    },
  });
  const activeSubmission = evaluation.data?.id === current?.id ? evaluation.data : current;

  function selectSubmission(submission: Submission) {
    setCurrent(submission);
  }

  const checked = assignment.submissions.filter(
    (item) => item.status === "reviewed",
  );
  const assignedTotal = listItem.reviewer_total ?? assignment.submissions.length;
  // `listItem` is navigation state and can be stale after a save. The refreshed
  // assignment is the source of truth for the progress shown on this screen.
  const assignedChecked = checked.length;

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
      return submission;
    },
    onSuccess: async (submission) => {
      selectSubmission(submission);
      await onRefresh();
    },
  });

  return (
    <div className="space-y-5">
      <section className="card p-5">
        <div className="flex flex-wrap items-center gap-3">
          <ResourceLinks taskUrl={assignment.task_url} taskFileUrl={assignment.task_file_url} criteriaUrl={assignment.criteria_url} />
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
                  <span className="font-mono text-xs text-muted">{formatScore(criterion.max_score)} б.</span>
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

      <section className="card">
        <div className="flex items-center justify-between border-b border-border px-5 py-4">
          <h2 className="text-sm font-semibold">Проверенные студенты</h2>
          <span className="font-mono text-xs text-muted">{checked.length} записей</span>
        </div>
        <div>
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
                  <td className="px-4 py-3 text-center font-mono font-semibold">{formatScore(student.score)}</td>
                  <td className="px-4 py-3 text-center">
                    <span className={`rounded-md px-2 py-0.5 ${student.integrity_flag ? "bg-red-50 text-danger" : "bg-emerald-50 text-success"}`}>
                      {student.integrity_flag ? "Есть сигнал" : "Нет"}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-right">
                    <button
                      className="font-medium text-accent hover:underline"
                      onClick={() => {
                        void homeworkApi.getSubmission(student.id).then(selectSubmission);
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
  onCancel,
  onSaved,
}: {
  submission: Submission;
  criteria: Criterion[];
  onCancel: () => void;
  onSaved: () => Promise<void>;
}) {
  type EditableScore = {
    criterion_index: number;
    score: number | "";
    comment: string;
  };
  const structuredScores = submission.review_json?.criterion_results ?? [];
  const [summary, setSummary] = useState(
    submission.summary ?? submission.ai_draft?.summary ?? submission.review_json?.summary_feedback ?? "",
  );
  const [integrity, setIntegrity] = useState(submission.integrity_flag ?? "");
  const [reviewMode, setReviewMode] = useState<"approve" | "modify" | "changes">("approve");
  const [scoresEdited, setScoresEdited] = useState(false);
  const [scores, setScores] = useState<EditableScore[]>(() =>
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
        score: saved?.score ?? draft?.score ?? structured?.assigned_score ?? "",
        comment: saved?.comment ?? draft?.comment ?? structured?.reasoning ?? "",
      };
    }),
  );
  const scoreFromCriteria = sumScores(structuredScores.map((item) => item.assigned_score));
  const scoreFromDraft = sumScores(submission.ai_draft?.scores.map((item) => item.score) ?? []);
  const persistedScore = structuredScores.length > 0
    ? scoreFromCriteria
    : submission.ai_draft?.scores.length
      ? scoreFromDraft
      : submission.review_json?.total_score;
  // A saved reviewer score is authoritative, even when an AI result is present.
  const enteredTotal = sumScores(scores.map((item) => item.score));
  const totalScore = scoresEdited || submission.criterion_scores?.length
    ? enteredTotal
    : persistedScore ?? enteredTotal;
  const maximumScore = sumScores(criteria.map((criterion) => criterion.max_score));
  const hasScoreData = Boolean(
    submission.criterion_scores?.length ||
    submission.ai_draft?.scores?.length ||
    structuredScores.length ||
    submission.review_json?.total_score != null,
  );
  const totalDisplay = hasScoreData ? `${formatScore(totalScore)}/${formatScore(maximumScore)}` : "-";
  const integrityStatus = submission.ai_assessment_json?.status;
  const evaluationBanner = submission.evaluation_status === "queued" || submission.evaluation_status === "processing"
    ? { text: "AI-проверка выполняется. Результаты появятся автоматически.", className: "border-white/30 bg-white/15 text-white" }
    : submission.evaluation_status === "completed"
      ? { text: "AI-проверка завершена", className: "border-emerald-200 bg-emerald-50 text-emerald-800" }
      : submission.evaluation_status === "failed"
        ? { text: "Не удалось выполнить AI-проверку.", className: "border-red-200 bg-red-50 text-red-800" }
        : null;
  const save = useMutation({
    mutationFn: () =>
      homeworkApi.saveReview(submission.id, {
        criterion_scores: scores.map((item) => ({ ...item, score: item.score === "" ? 0 : item.score })),
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
    <section className="rounded-xl border border-accent bg-white shadow-lg">
      <div className="bg-gradient-to-r from-primary to-accent px-5 py-5 text-white">
        <p className="text-xs font-semibold uppercase tracking-wider text-white/70">AI-отчёт · автоматический анализ</p>
        <h2 className="mt-1 font-display text-2xl">{submission.student_name}</h2>
        <div className="mt-2 flex gap-4 text-xs">
          <a href={submission.stepik_url} target="_blank" rel="noreferrer" className="underline">Stepik ↗</a>
          <a href={submission.work_url} target="_blank" rel="noreferrer" className="underline">Открыть работу ↗</a>
        </div>
        {evaluationBanner && (
          <div className={`mt-4 rounded-lg border px-3 py-2 text-sm ${evaluationBanner.className}`}>
            {evaluationBanner.text}
          </div>
        )}
      </div>

      <form className="space-y-5 p-5" onSubmit={submit}>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          <Metric label="Итоговый балл" value={totalDisplay} />
          <Metric label="Критерии" value={String(criteria.length)} />
          <Metric
            label="Самостоятельность выполнения"
            status={integrityStatus}
          />
        </div>

        <div className="rounded-lg border border-border bg-secondary p-4">
          <p className="eyebrow">Текстовый отчёт</p>
          <p className="text-sm leading-6 text-slate-700">
            {submission.ai_draft?.summary ?? submission.review_json?.summary_feedback ?? submission.summary ?? "Сохранённая проверка доступна для редактирования."}
          </p>
        </div>

        <label className="block">
          <span className="field-label">Общий комментарий ревьюера</span>
          <textarea rows={4} value={summary} onChange={(event) => setSummary(event.target.value)} required />
        </label>
        <section>
          <div className="mb-3 flex items-center justify-between gap-3">
            <div>
              <p className="eyebrow">Финальное решение</p>
              <h3 className="text-sm font-semibold">Оценки по критериям</h3>
            </div>
            <span className="font-mono text-lg font-semibold">{totalDisplay}</span>
          </div>
          <div className="space-y-3">
            {submission.ai_draft?.scores || structuredScores.length > 0 ? (
              <div className="grid gap-2 rounded-lg border border-border bg-secondary p-3">
                {(submission.ai_draft?.scores ?? structuredScores.map((item) => ({
                  criterion: item.criterion_name,
                  score: item.assigned_score,
                  max_score: item.max_points,
                  comment: item.reasoning,
                  evidence: item.evidence,
                }))).map((item) => {
                  const rubricCriterion = criteria.find((criterion) => criterion.title === item.criterion);
                  return (
                    <div key={item.criterion} className="flex gap-3 rounded-lg bg-white p-3 text-xs">
                      <span className="min-w-0 flex-1">
                        <strong>{item.criterion}</strong>
                        {rubricCriterion?.description ? <span className="mt-1 block text-muted">{rubricCriterion.description}</span> : null}
                        <span className="mt-1 block text-muted">{item.comment}</span>
                      </span>
                      <span className="shrink-0 font-mono font-semibold">{formatScore(item.score)}/{formatScore(item.max_score)}</span>
                    </div>
                  );
                })}
              </div>
            ) : null}
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
                    <span className="field-label">Балл из {formatScore(criterion.max_score)}</span>
                    <input
                      type="number"
                      step="any"
                      min={0}
                      max={criterion.max_score}
                      value={scores[index].score}
                      onChange={(event) => {
                        setScoresEdited(true);
                        const rawScore = event.target.value;
                        setScores((current) =>
                          current.map((item, itemIndex) =>
                            itemIndex === index
                              ? { ...item, score: rawScore === "" ? "" : parseScore(rawScore) }
                              : item,
                          ),
                        );
                      }}
                      onBlur={() =>
                        setScores((current) =>
                          current.map((item, itemIndex) =>
                            itemIndex === index && item.score === "" ? { ...item, score: 0 } : item,
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
          <button
            type="submit"
            className="button-success"
            disabled={save.isPending || submission.evaluation_status === "queued" || submission.evaluation_status === "processing"}
            onClick={() => setReviewMode("approve")}
          >
            Одобрить AI-проверку
          </button>
          <button type="button" className="button-secondary" onClick={() => setReviewMode("modify")}>Подтвердить и сохранить изменения</button>
          <button
            type="button"
            className="button-secondary"
            onClick={() => {
              setReviewMode("changes");
              setSummary((current) => current.trim() ? current : "Требуется доработка: ");
            }}
          >
            Отклонить / запросить доработку
          </button>
          <button type="submit" className="button-primary" disabled={save.isPending || submission.evaluation_status === "queued" || submission.evaluation_status === "processing"}>
            Подтвердить и сохранить изменения
          </button>
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
        <label className="block border-t border-border pt-5">
          <span className="field-label">Комментарий об использовании AI</span>
          <textarea
            rows={2}
            value={integrity}
            onChange={(event) => setIntegrity(event.target.value)}
            placeholder={submission.ai_draft?.integrity.reason ?? "Оставьте пустым, если нарушений нет"}
          />
        </label>
        {reviewMode === "modify" && <p className="text-xs text-accent">Измените баллы и комментарии, затем отправьте итоговую проверку.</p>}
        {reviewMode === "changes" && <p className="text-xs text-warning">Укажите, что нужно доработать, затем отправьте итоговую проверку.</p>}
      </form>
    </section>
  );
}


function Metric({ label, value, status }: { label: string; value?: string; status?: string }) {
  const statusClass = {
    green: "bg-emerald-500",
    yellow: "bg-amber-400",
    red: "bg-red-500",
  }[status ?? ""];
  return (
    <div className="flex flex-col items-center justify-center rounded-lg border border-border bg-white p-3 text-center">
      {status === undefined ? (
        <p className="font-mono text-lg font-semibold">{value}</p>
      ) : statusClass ? (
        <span
          aria-label={`Статус самостоятельности: ${status}`}
          className={`block h-[26px] w-[26px] rounded-full ${statusClass}`}
        />
      ) : null}
      <p className="mt-0.5 text-[10px] text-muted">{label}</p>
    </div>
  );
}


function ExternalTextLink({ href, children }: { href: string; children: React.ReactNode }) {
  return <a href={href} target="_blank" rel="noreferrer" className="text-accent hover:underline">{children} ↗</a>;
}
