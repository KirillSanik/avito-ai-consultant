import type {
  Assignment,
  AuthResponse,
  Course,
  CourseCreate,
  CourseReviewer,
  Dashboard,
  EnrollmentApplication,
  HomeworkCreate,
  HomeworkListItem,
  Reviewer,
  Role,
  Submission,
  User,
  XlsxImportResult,
} from "./types";
import { activityLogger } from "./logger";


export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const AUTH_STORAGE_KEY = "reviewdesk.session";

let authToken: string | null = null;

export function setAuthToken(token: string | null) {
  authToken = token;
}

export function persistSession(auth: AuthResponse | null) {
  if (typeof window === "undefined") return;
  if (auth) {
    localStorage.setItem(AUTH_STORAGE_KEY, JSON.stringify(auth));
    setAuthToken(auth.token);
    return;
  }
  localStorage.removeItem(AUTH_STORAGE_KEY);
  setAuthToken(null);
}

export function loadSession(): AuthResponse | null {
  if (typeof window === "undefined") return null;
  const raw = localStorage.getItem(AUTH_STORAGE_KEY);
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw) as AuthResponse;
    if (!parsed?.token || !parsed.user?.login) return null;
    setAuthToken(parsed.token);
    return parsed;
  } catch {
    localStorage.removeItem(AUTH_STORAGE_KEY);
    return null;
  }
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const method = init?.method ?? "GET";
  const started = Date.now();
  activityLogger.info("api.request", { method, path });
  let response: Response;
  try {
    response = await fetch(`${API_URL}${path}`, {
      ...init,
      headers: {
        "Content-Type": "application/json",
        ...(authToken ? { Authorization: `Bearer ${authToken}` } : {}),
        ...init?.headers,
      },
    });
  } catch (error) {
    activityLogger.error("api.network_error", { method, path, error: String(error) });
    throw new Error("Сервис временно недоступен. Повторите попытку.");
  }

  if (!response.ok) {
    activityLogger.error("api.response.error", { method, path, status: response.status, durationMs: Date.now() - started });
    const body = await response.json().catch(() => ({ detail: "Ошибка API" }));
    const detail = Array.isArray(body.detail)
      ? body.detail.map((item: { msg?: string }) => item.msg).filter(Boolean).join(", ")
      : body.detail;
    throw new Error(detail || "Не удалось выполнить запрос");
  }
  activityLogger.info("api.response.ok", { method, path, status: response.status, durationMs: Date.now() - started });
  if (response.status === 204) return undefined as T;
  return response.json();
}

async function requestError(response: Response): Promise<Error> {
  const body = await response.json().catch(() => ({ detail: "Ошибка API" }));
  const detail = Array.isArray(body.detail)
    ? body.detail.map((item: { msg?: string }) => item.msg).filter(Boolean).join(", ")
    : body.detail;
  return new Error(detail || "Не удалось выполнить запрос");
}

export async function downloadBlob(path: string, filename: string) {
  activityLogger.info("download.start", { path, filename });
  const response = await fetch(`${API_URL}${path}`, {
    headers: {
      ...(authToken ? { Authorization: `Bearer ${authToken}` } : {}),
    },
  });
  if (!response.ok) throw await requestError(response);
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
  activityLogger.info("download.complete", { path, filename });
}

export async function uploadXlsx(
  path: string,
  file: File,
  confirm = false,
): Promise<XlsxImportResult> {
  const form = new FormData();
  form.append("file", file);
  const separator = path.includes("?") ? "&" : "?";
  const response = await fetch(
    `${API_URL}${path}${separator}confirm=${confirm ? "true" : "false"}`,
    {
      method: "POST",
      headers: {
        ...(authToken ? { Authorization: `Bearer ${authToken}` } : {}),
      },
      body: form,
    },
  );
  if (!response.ok) throw await requestError(response);
  return response.json();
}

export const authApi = {
  login: (login: string, password: string) =>
    api<AuthResponse>("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ login, password }),
    }),
  register: (payload: {
    login: string;
    password: string;
    first_name: string;
    last_name: string;
    telegram: string;
    role: Role;
  }) =>
    api<AuthResponse>("/api/auth/register", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  me: () => api<AuthResponse["user"]>("/api/auth/me"),
};

export const courseApi = {
  list: (asReviewer = false) =>
    api<Course[]>(asReviewer ? "/api/courses?as_reviewer=true" : "/api/courses"),
  create: (payload: CourseCreate) =>
    api<Course>("/api/courses", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  updateDescription: (courseId: number, description: string) =>
    api<Course>(`/api/courses/${courseId}`, {
      method: "PATCH",
      body: JSON.stringify({ description }),
    }),
  homeworks: (courseId: number, asReviewer = false) =>
    api<HomeworkListItem[]>(
      `/api/courses/${courseId}/assignments${asReviewer ? "?as_reviewer=true" : ""}`,
    ),
  createHomework: (courseId: number, payload: HomeworkCreate) =>
    api<HomeworkListItem>(`/api/courses/${courseId}/assignments`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  reviewerCatalog: () => api<User[]>("/api/reviewers"),
  reviewers: (courseId: number) =>
    api<CourseReviewer[]>(`/api/courses/${courseId}/reviewers`),
  addReviewer: (courseId: number, userId: number) =>
    api<CourseReviewer>(`/api/courses/${courseId}/reviewers`, {
      method: "POST",
      body: JSON.stringify({ user_id: userId }),
    }),
  removeReviewer: (courseId: number, userId: number) =>
    api(`/api/courses/${courseId}/reviewers/${userId}`, { method: "DELETE" }),
  exportXlsx: (courseId: number) =>
    downloadBlob(`/api/courses/${courseId}/export.xlsx`, `course-${courseId}.xlsx`),
  importReviewers: (courseId: number, file: File, confirm = false) =>
    uploadXlsx(`/api/courses/${courseId}/reviewers/import`, file, confirm),
};

export const applicationApi = {
  list: (
    status: EnrollmentApplication["status"] = "pending",
    courseId?: number,
  ) =>
    api<EnrollmentApplication[]>(
      `/api/enrollment-applications?status=${status}${
        courseId ? `&course_id=${courseId}` : ""
      }`,
    ),
  decide: (id: number, status: "enrolled" | "rejected") =>
    api<EnrollmentApplication>(`/api/enrollment-applications/${id}`, {
      method: "PATCH",
      body: JSON.stringify({ status }),
    }),
};

export const homeworkApi = {
  get: (id: number, asReviewer = false) =>
    api<Assignment>(`/api/assignments/${id}${asReviewer ? "?as_reviewer=true" : ""}`),
  getSubmission: (id: number) => api<Submission>(`/api/submissions/${id}`),
  next: (id: number) => api<Submission>(`/api/assignments/${id}/next`),
  createDraft: (submissionId: number) =>
    api<Submission>(`/api/submissions/${submissionId}/ai-draft`, { method: "POST" }),
  uploadTaskFile: (assignmentId: number, file: File) => {
    const form = new FormData();
    form.append("file", file);
    return fetch(`${API_URL}/api/assignments/${assignmentId}/task-file`, {
      method: "POST",
      headers: authToken ? { Authorization: `Bearer ${authToken}` } : {},
      body: form,
    }).then(async (response) => {
      if (!response.ok) throw await requestError(response);
      return response.json();
    });
  },
  saveReview: (
    submissionId: number,
    payload: {
      criterion_scores: Array<{
        criterion_index: number;
        score: number;
        comment: string;
      }>;
      summary: string;
      integrity_flag: string | null;
    },
  ) =>
    api<Submission>(`/api/submissions/${submissionId}/review`, {
      method: "PUT",
      body: JSON.stringify(payload),
    }),
  clarify: (id: number, message: string) =>
    api(`/api/assignments/${id}/clarifications`, {
      method: "POST",
      body: JSON.stringify({ message }),
    }),
  updateCriteria: (id: number, criteria: Assignment["criteria"], reviewerGuide: string) =>
    api<Assignment>(`/api/assignments/${id}/criteria`, {
      method: "PUT",
      body: JSON.stringify({ criteria, reviewer_guide: reviewerGuide }),
    }),
  reviewers: (id: number) => api<Reviewer[]>(`/api/assignments/${id}/reviewers`),
  addReviewer: (id: number, userId: number) =>
    api<Reviewer>(`/api/assignments/${id}/reviewers`, {
      method: "POST",
      body: JSON.stringify({ user_id: userId }),
    }),
  addReviewersBulk: (id: number, userIds: number[]) =>
    api<Reviewer[]>(`/api/assignments/${id}/reviewers/bulk`, {
      method: "POST",
      body: JSON.stringify({ user_ids: userIds }),
    }),
  removeReviewer: (assignmentId: number, reviewerId: number) =>
    api(`/api/assignments/${assignmentId}/reviewers/${reviewerId}`, { method: "DELETE" }),
  updateClarification: (id: number, status: "accepted" | "rejected" | "dismissed") =>
    api(`/api/clarifications/${id}`, {
      method: "PATCH",
      body: JSON.stringify({ status }),
    }),
  dashboard: () => api<Dashboard>("/api/dashboard"),
  exportXlsx: (id: number) =>
    downloadBlob(`/api/assignments/${id}/export.xlsx`, `assignment-${id}.xlsx`),
  importReviewers: (id: number, file: File, confirm = false) =>
    uploadXlsx(`/api/assignments/${id}/reviewers/import`, file, confirm),
  downloadReport: (id: number) =>
    downloadBlob(`/api/submissions/${id}/report.pdf`, `review-${id}.pdf`),
};
