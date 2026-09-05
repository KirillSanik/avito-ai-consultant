TASK_RUBRIC_SYSTEM_PROMPT = "Extract a Russian homework rubric. Return JSON with title, description, guidelines, criteria, constraints. Each criterion must contain name, description, min_points, max_points."
GRADING_SYSTEM_PROMPT = "Grade exactly one homework criterion. Return JSON with assigned_score, reasoning, evidence. Scores must not exceed max_points."
AI_ORIGIN_SYSTEM_PROMPT = "Assess whether a submitted repository shows AI-generated code. Return JSON with ai_indicators, human_indicators, reasoning, status (green/yellow/red), confidence (0..1)."
