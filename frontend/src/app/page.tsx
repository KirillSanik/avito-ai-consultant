"use client";

import { useEffect, useState } from "react";

import { PageLoader } from "@/components/ui";
import { authApi, loadSession, persistSession } from "@/lib/api";
import type { AuthResponse, Course, HomeworkListItem, Role } from "@/lib/types";
import { ApplicationsScreen } from "@/screens/ApplicationsScreen";
import { AuthScreen } from "@/screens/AuthScreen";
import { CoursesScreen } from "@/screens/CoursesScreen";
import { HomeworkDetailScreen } from "@/screens/HomeworkDetailScreen";
import { HomeworksScreen } from "@/screens/HomeworksScreen";


type Screen = "auth" | "courses" | "applications" | "homeworks" | "homework";

export default function Home() {
  const [screen, setScreen] = useState<Screen>("auth");
  const [session, setSession] = useState<AuthResponse | null>(null);
  const [role, setRole] = useState<Role>("reviewer");
  const [course, setCourse] = useState<Course | null>(null);
  const [homework, setHomework] = useState<HomeworkListItem | null>(null);
  const [restoring, setRestoring] = useState(true);

  useEffect(() => {
    let cancelled = false;

    async function restoreSession() {
      const stored = loadSession();
      if (!stored) {
        if (!cancelled) setRestoring(false);
        return;
      }
      try {
        const user = await authApi.me();
        if (cancelled) return;
        const restored = { token: stored.token, user };
        persistSession(restored);
        setSession(restored);
        setRole(user.role);
        setScreen("courses");
      } catch {
        persistSession(null);
      } finally {
        if (!cancelled) setRestoring(false);
      }
    }

    void restoreSession();
    return () => {
      cancelled = true;
    };
  }, []);

  function authenticated(auth: AuthResponse) {
    persistSession(auth);
    setSession(auth);
    setRole(auth.user.role);
    setScreen("courses");
  }

  function logout() {
    persistSession(null);
    setSession(null);
    setCourse(null);
    setHomework(null);
    setRole("reviewer");
    setScreen("auth");
  }

  if (restoring) {
    return (
      <main className="min-h-screen bg-background">
        <PageLoader label="Проверяем сессию…" />
      </main>
    );
  }

  if (screen === "auth" || !session) {
    return <AuthScreen onAuthenticated={authenticated} />;
  }

  if (screen === "courses") {
    return (
      <CoursesScreen
        role={role}
        accountRole={session.user.role}
        onRoleChange={setRole}
        onLogout={logout}
        onApplications={() => setScreen("applications")}
        onSelect={(selected) => {
          setCourse(selected);
          setScreen("homeworks");
        }}
      />
    );
  }

  if (screen === "applications" && session.user.role === "methodist") {
    return (
      <ApplicationsScreen
        onBack={() => setScreen("courses")}
        onLogout={logout}
      />
    );
  }

  if (screen === "homeworks" && course) {
    return (
      <HomeworksScreen
        course={course}
        role={role}
        onBack={() => setScreen("courses")}
        onSelect={(selected) => {
          setHomework(selected);
          setScreen("homework");
        }}
        currentUser={session.user}
      />
    );
  }

  if (screen === "homework" && course && homework) {
    return (
      <HomeworkDetailScreen
        course={course}
        homework={homework}
        role={role}
        onBack={() => setScreen("homeworks")}
      />
    );
  }

  return null;
}
