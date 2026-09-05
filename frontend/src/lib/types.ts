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
  id: number;
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
  id: number;
  user_id: number;
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
  deadline: string;
  task_url: string;
  criteria_url?: string;
  number?: number;
  reviewer_guide?: string;
  criteria?: Criterion[];
  reviewer_user_ids?: number[];
};

export type HomeworkListItem = {
  id: number;
  title: string;
  number?: number;
  deadline: string;
  task_url?: string;
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
  evidence?: string[];
};

export type EvaluationReport = {
  task_id: string;
  submission_id: string;
  total_score: number;
  max_total_score: number;
  criterion_results: Array<{
    criterion_id: string;
    criterion_name: string;
    assigned_score: number;
    max_points: number;
    reasoning: string;
    evidence: string[];
  }>;
  summary_feedback: string;
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
  source_type?: string;
  source_file_path?: string | null;
  evaluation_status?: "not_requested" | "queued" | "processing" | "completed" | "failed" | "stale";
  latest_evaluation_id?: number | null;
  review_json?: EvaluationReport | null;
  ai_assessment_json?: {
    status: string;
    confidence: number;
    reasoning: string;
    ai_indicators: string[];
    human_indicators: string[];
  } | null;
  pdf_report_path?: string | null;
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
  rubric_status?: string;
  rubric_json?: Record<string, unknown> | null;
  task_text?: string | null;
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
