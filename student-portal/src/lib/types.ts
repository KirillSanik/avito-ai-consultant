export type StudentUser = {
  id: number;
  login: string;
  first_name: string;
  last_name: string;
  telegram: string;
  role: "student";
};

export type AuthResponse = {
  token: string;
  user: StudentUser;
};

export type StudentSubmission = {
  id: number;
  work_url: string;
  status: string;
  score: number | null;
  summary: string | null;
};

export type StudentAssignment = {
  id: number;
  title: string;
  number: number;
  deadline: string;
  task_url: string;
  submission: StudentSubmission | null;
};

export type EnrollmentStatus = "none" | "pending" | "enrolled" | "rejected";

export type StudentCourse = {
  id: number;
  title: string;
  year: number;
  cohort: string;
  stream: number;
  active: boolean;
  cover_color: string;
  description: string;
  capacity: number;
  enrolled_count: number;
  enrollment_status: EnrollmentStatus;
  total_points: number;
};

export type StudentCourseDetail = StudentCourse & {
  assignments: StudentAssignment[];
};
