export type ActivityLevel = "debug" | "info" | "warn" | "error";

const STORAGE_KEY = "reviewdesk.activity.log";
const MAX_ENTRIES = 200;

type ActivityEntry = {
  timestamp: string;
  level: ActivityLevel;
  event: string;
  details?: Record<string, unknown>;
};

function write(level: ActivityLevel, event: string, details?: Record<string, unknown>) {
  const entry: ActivityEntry = { timestamp: new Date().toISOString(), level, event, details };
  const consoleMethod = console[level] ?? console.log;
  consoleMethod(`[ReviewDesk] ${entry.timestamp} ${event}`, details ?? "");
  if (typeof window === "undefined") return;
  try {
    const previous = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? "[]") as ActivityEntry[];
    localStorage.setItem(STORAGE_KEY, JSON.stringify([...previous, entry].slice(-MAX_ENTRIES)));
  } catch {
    return;
  }
}

export const activityLogger = {
  debug: (event: string, details?: Record<string, unknown>) => write("debug", event, details),
  info: (event: string, details?: Record<string, unknown>) => write("info", event, details),
  warn: (event: string, details?: Record<string, unknown>) => write("warn", event, details),
  error: (event: string, details?: Record<string, unknown>) => write("error", event, details),
  read: (): ActivityEntry[] => {
    if (typeof window === "undefined") return [];
    try {
      return JSON.parse(localStorage.getItem(STORAGE_KEY) ?? "[]") as ActivityEntry[];
    } catch {
      return [];
    }
  },
  clear: () => {
    if (typeof window !== "undefined") localStorage.removeItem(STORAGE_KEY);
  },
};
