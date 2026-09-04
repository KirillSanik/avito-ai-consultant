import type {
  AuthResponse,
  StudentAssignment,
  StudentCourse,
  StudentCourseDetail,
  StudentSubmission,
} from "./types";


const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const STORAGE_KEY = "studentdesk.session";
let token: string | null = null;


export function saveSession(session: AuthResponse | null) {
  if (typeof window === "undefined") return;
  if (session) {
    token = session.token;
    localStorage.setItem(STORAGE_KEY, JSON.stringify(session));
  } else {
    token = null;
    localStorage.removeItem(STORAGE_KEY);
  }
}


export function loadSession(): AuthResponse | null {
  if (typeof window === "undefined") return null;
  const raw = localStorage.getItem(STORAGE_KEY);
  if (!raw) return null;
  try {
    const session = JSON.parse(raw) as AuthResponse;
    if (!session.token || session.user.role !== "student") return null;
    token = session.token;
    return session;
  } catch {
    localStorage.removeItem(STORAGE_KEY);
    return null;
  }
}


async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...init?.headers,
    },
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({ detail: "Ошибка API" }));
    const detail = Array.isArray(body.detail)
      ? body.detail.map((item: { msg?: string }) => item.msg).filter(Boolean).join(", ")
      : body.detail;
    throw new Error(detail || "Не удалось выполнить запрос");
  }
  return response.status === 204 ? (undefined as T) : response.json();
}


export const studentAuthApi = {
  login: (login: string, password: string) =>
    api<AuthResponse>("/api/student/auth/login", {
      method: "POST",
      body: JSON.stringify({ login, password }),
    }),
  register: (payload: {
    login: string;
    password: string;
    first_name: string;
    last_name: string;
    telegram: string;
  }) =>
    api<AuthResponse>("/api/student/auth/register", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  me: () => api<AuthResponse["user"]>("/api/student/auth/me"),
};


export const studentCourseApi = {
  list: () => api<StudentCourse[]>("/api/student/courses"),
  mine: () => api<StudentCourse[]>("/api/student/courses/mine"),
  get: (id: number) => api<StudentCourseDetail>(`/api/student/courses/${id}`),
  apply: (id: number) =>
    api(`/api/student/courses/${id}/apply`, { method: "POST" }),
};


export const studentHomeworkApi = {
  get: (id: number) =>
    api<StudentAssignment>(`/api/student/assignments/${id}`),
  submit: (id: number, workUrl: string) =>
    api<StudentSubmission>(`/api/student/assignments/${id}/submit`, {
      method: "POST",
      body: JSON.stringify({ work_url: workUrl }),
    }),
};
