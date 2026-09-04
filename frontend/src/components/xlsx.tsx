"use client";

import { useState } from "react";

import type { XlsxImportResult } from "@/lib/types";


export function XlsxImportCard({
  title,
  hint,
  onPreview,
  onConfirm,
  onApplied,
}: {
  title: string;
  hint: string;
  onPreview: (file: File) => Promise<XlsxImportResult>;
  onConfirm: (file: File) => Promise<XlsxImportResult>;
  onApplied?: () => Promise<unknown> | unknown;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<XlsxImportResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function previewFile() {
    if (!file) return;
    setBusy(true);
    setError(null);
    try {
      setPreview(await onPreview(file));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Не удалось прочитать файл");
    } finally {
      setBusy(false);
    }
  }

  async function confirmImport() {
    if (!file) return;
    setBusy(true);
    setError(null);
    try {
      const result = await onConfirm(file);
      setPreview(result);
      await onApplied?.();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Не удалось импортировать");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="rounded-lg border border-dashed border-border p-4">
      <p className="text-sm font-medium">{title}</p>
      <p className="mt-1 text-xs text-muted">{hint}</p>
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <input
          type="file"
          accept=".xlsx"
          onChange={(event) => {
            setFile(event.target.files?.[0] ?? null);
            setPreview(null);
          }}
        />
        <button
          type="button"
          className="button-secondary py-1.5 text-xs"
          disabled={!file || busy}
          onClick={() => void previewFile()}
        >
          Проверить файл
        </button>
      </div>
      {error && <p className="mt-2 text-xs text-danger">{error}</p>}
      {preview && (
        <div className="mt-3 space-y-1 text-xs">
          <p>Будут назначены: {preview.added.length ? preview.added.join(", ") : "никого"}</p>
          <p>Пропущены: {preview.skipped.length ? preview.skipped.join(", ") : "нет"}</p>
          {preview.errors.map((item) => (
            <p key={item} className="text-danger">{item}</p>
          ))}
          {preview.applied ? (
            <p className="text-success">Назначение сохранено</p>
          ) : (
            <button
              type="button"
              className="button-primary mt-2 py-1.5 text-xs"
              disabled={busy || !preview.added.length}
              onClick={() => void confirmImport()}
            >
              Подтвердить назначение
            </button>
          )}
        </div>
      )}
    </div>
  );
}
