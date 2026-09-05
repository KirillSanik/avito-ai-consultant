export type Role = "reviewer" | "methodist";

export type User = {
  id: number;
  login: string;
  first_name: string;
  last_name: string;
  telegram: string;
  role: Role;
};

export type AuthResponse = {
  token: string;
  user: User;
};

export type Course = {
  id: string;
  title: string;
  year: number;
  cohort: string;
  stream?: number;
  active?: boolean;
  cover_color?: string;
  students_count?: number;
  assignments_count?: number;
  description?: string;
  capacity?: number;
  enrolled_count?: number;
};

export type CourseReviewer = {
  id: string;
  user_id: string;
  login: string;
  first_name: string;
  last_name: string;
  telegram: string;
};

export type CourseCreate = {
  title: string;
  year: number;
  cohort: string;
  stream: number;
  active?: boolean;
  cover_color?: string;
  students_count?: number;
  description?: string;
  capacity?: number;
};

export type EnrollmentApplication = {
  id: number;
  course_id: number;
  course_title: string;
  student_id: number;
  student_name: string;
  student_login: string;
  student_telegram: string;
  status: "pending" | "enrolled" | "rejected";
  created_at: string;
  decided_at: string | null;
};

export type HomeworkCreate = {
  title: string;
  description: string;
  deadline: string;
  url?: string;
  file?: File;
};

export type HomeworkListItem = {
  id: string;
  course_id: string;
  title: string;
  description: string;
  number?: number;
  deadline: string;
  task_url?: string;
  criteria?: Criterion[];
  criteria_url?: string;
  total: number;
  reviewed: number;
  reviewer_checked?: number;
  reviewer_total?: number;
};

export type Criterion = {
  title: string;
  max_score: number;
  description?: string;
};

export type DraftScore = {
  criterion: string;
  score: number;
  max_score: number;
  comment: string;
};

export type CriterionScore = {
  criterion_index: number;
  criterion: string;
  score: number;
  max_score: number;
  comment: string;
};

export type Submission = {
  id: number;
  student_name: string;
  work_url: string;
  stepik_url: string;
  status: "pending" | "in_review" | "reviewed";
  reviewer: string | null;
  score: number | null;
  summary: string | null;
  integrity_flag: string | null;
  reviewer_user_id: number | null;
  criterion_scores: CriterionScore[] | null;
  ai_draft: {
    scores: DraftScore[];
    total: number;
    summary: string;
    integrity: { confidence: number; reason: string };
  } | null;
};

export type Assignment = {
  id: number;
  course_id: number;
  title: string;
  number?: number;
  deadline: string;
  task_url: string;
  criteria_url?: string;
  criteria: Criterion[];
  reviewer_guide: string;
  submissions: Submission[];
};

export type Reviewer = {
  id: number;
  name: string;
  telegram: string;
  checked: number;
  total: number;
  anomaly: boolean;
  user_id?: number | null;
};

export type Clarification = {
  id: number;
  assignment_id: number;
  author: string;
  message: string;
  status: "open" | "accepted" | "rejected" | "dismissed";
  created_at: string;
};

export type Dashboard = {
  courses: Course[];
  pending_reviews_count: number;
  active_homeworks_count: number;
  total: number;
  reviewed: number;
  in_progress: number;
  reviewers: Reviewer[];
  clarifications: Clarification[];
};

export type XlsxImportResult = {
  added: string[];
  skipped: string[];
  errors: string[];
  applied: boolean;
};
