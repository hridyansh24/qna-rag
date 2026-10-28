import { useRef, useState } from 'react';
import {
  AlertTriangle,
  CheckCircle2,
  Clock,
  FileUp,
  GitBranch,
  Globe,
  Loader2,
  MessagesSquare,
  RefreshCw,
  Trash2,
  XCircle,
} from 'lucide-react';
import { api } from '../../lib/api';
import type { IngestionRun, Resource, SkippedFile, UploadResult } from '../../lib/types';
import { Badge } from '../ui/badge';
import { Button } from '../ui/button';
import { Card } from '../ui/card';
import { Input } from '../ui/input';
import { cn } from '../../lib/utils';
import { UPLOAD_ACCEPT, UploadSummary } from './AddResourceForm';
import { timeAgo } from './fields';

const TYPE_LABELS: Record<Resource['resource_type'], string> = {
  SYLLABUS: 'Syllabus',
  SCHEDULE: 'Schedule',
  REPOSITORY: 'Repository',
  QA_HISTORY: 'Q&A history',
};

export function isActive(run: IngestionRun | null | undefined): boolean {
  return run?.status === 'QUEUED' || run?.status === 'RUNNING';
}

/**
 * One resource: where it comes from, and its latest run in every profile,
 * with Sync per profile. A resource with any active run can't be replaced
 * or deleted (the backend returns 409; §7.5), so those buttons wait too.
 */
export function ResourceCard({
  courseId,
  resource,
  profiles,
  onChange,
}: {
  courseId: number;
  resource: Resource;
  profiles: string[];
  onChange: () => Promise<void>;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [replacing, setReplacing] = useState(false);
  const anyActive = Object.values(resource.latest_runs).some(isActive);

  async function run(action: () => Promise<unknown>) {
    setBusy(true);
    setError('');
    try {
      await action();
      await onChange();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Request failed');
    } finally {
      setBusy(false);
    }
  }

  function handleDelete() {
    if (!window.confirm(`Delete “${resource.display_name}”? Its files and indexed chunks are removed from every profile.`)) {
      return;
    }
    void run(() => api.delete(`/courses/${courseId}/resources/${resource.id}`));
  }

  return (
    <Card className="overflow-hidden">
      <div className="px-5 py-4">
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0">
            <p className="flex items-center gap-2 font-semibold text-fg">
              <SourceIcon resource={resource} />
              {resource.display_name}
              <Badge variant="outline">{TYPE_LABELS[resource.resource_type]}</Badge>
            </p>
            <SourceLine resource={resource} />
          </div>
          <div className="flex shrink-0 gap-2">
            {resource.source_kind === 'UPLOAD' && (
              <Button
                size="sm"
                variant="outline"
                disabled={busy || anyActive}
                onClick={() => setReplacing((r) => !r)}
                aria-expanded={replacing}
              >
                <FileUp size={14} className="mr-1.5" aria-hidden /> Replace file
              </Button>
            )}
            {resource.resource_type !== 'QA_HISTORY' && (
              <Button
                size="sm"
                variant="ghost"
                disabled={busy || anyActive}
                onClick={handleDelete}
                aria-label={`Delete ${resource.display_name}`}
                title={anyActive ? 'Wait for the running sync to finish' : 'Delete'}
              >
                <Trash2 size={14} aria-hidden />
              </Button>
            )}
          </div>
        </div>

        {resource.files.length > 0 && (
          <details className="mt-2 text-sm">
            <summary className="cursor-pointer text-fg-muted">
              {resource.files.length} stored file{resource.files.length === 1 ? '' : 's'}
            </summary>
            <ul className="mt-1.5 max-h-40 overflow-auto font-mono text-xs text-fg-muted space-y-0.5">
              {resource.files.map((f) => (
                <li key={f}>{f}</li>
              ))}
            </ul>
          </details>
        )}

        {replacing && (
          <ReplaceForm
            courseId={courseId}
            resource={resource}
            onDone={async () => {
              setReplacing(false);
              await onChange();
            }}
          />
        )}

        {error && <p className="mt-2 text-danger text-sm">{error}</p>}
      </div>

      {profiles.length > 0 && (
        <ul className="border-t border-border bg-surface-sunken divide-y divide-border">
          {profiles.map((profile) => (
            <RunRow
              key={profile}
              profile={profile}
              run={resource.latest_runs[profile] ?? null}
              disabled={busy}
              onSync={() =>
                run(() => api.post(`/courses/${courseId}/resources/${resource.id}/sync`, { profile }))
              }
            />
          ))}
        </ul>
      )}
    </Card>
  );
}

function SourceIcon({ resource }: { resource: Resource }) {
  const props = { size: 16, className: 'shrink-0 text-accent-text', 'aria-hidden': true } as const;
  if (resource.source_kind === 'BOARD') return <MessagesSquare {...props} />;
  if (resource.source_kind === 'UPLOAD') return <FileUp {...props} />;
  if (resource.resource_type === 'REPOSITORY') return <GitBranch {...props} />;
  return <Globe {...props} />;
}

function SourceLine({ resource }: { resource: Resource }) {
  let text: string;
  if (resource.source_kind === 'BOARD') {
    text = 'Accepted answers on this board. Re-indexed automatically when an answer is verified.';
  } else if (resource.source_kind === 'UPLOAD') {
    text = `Uploaded · ${resource.upload_source_path ?? ''}`;
  } else {
    text = resource.url ?? '';
    if (resource.repo_ref) text += ` @ ${resource.repo_ref}`;
  }
  return (
    <p className="mt-1 text-sm text-fg-muted break-all">
      {text}
      {resource.last_commit_sha && (
        <span className="ml-2 font-mono text-xs">commit {resource.last_commit_sha.slice(0, 8)}</span>
      )}
    </p>
  );
}

function RunRow({
  profile,
  run,
  disabled,
  onSync,
}: {
  profile: string;
  run: IngestionRun | null;
  disabled: boolean;
  onSync: () => void;
}) {
  const active = isActive(run);
  return (
    <li className="px-5 py-2.5 text-sm">
      <div className="flex items-center justify-between gap-3">
        <div className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1">
          <span className="font-mono text-fg-secondary">{profile}</span>
          <RunStatus run={run} />
        </div>
        <Button
          size="sm"
          variant="outline"
          disabled={disabled || active}
          onClick={onSync}
          title={active ? 'This profile is already syncing this resource' : undefined}
        >
          <RefreshCw size={14} className={cn('mr-1.5', active && 'animate-spin')} aria-hidden />
          {run ? 'Re-sync' : 'Sync'}
        </Button>
      </div>
      {run?.status === 'FAILED' && run.error && (
        <p className="mt-1.5 flex items-start gap-1.5 text-danger">
          <XCircle size={14} className="mt-0.5 shrink-0" aria-hidden /> {run.error}
        </p>
      )}
      {run && run.skipped_files.length > 0 && <SkippedList skipped={run.skipped_files} />}
    </li>
  );
}

function RunStatus({ run }: { run: IngestionRun | null }) {
  if (!run) return <span className="text-fg-muted">Never synced</span>;
  switch (run.status) {
    case 'QUEUED':
      return (
        <span className="inline-flex items-center gap-1 text-fg-muted" role="status">
          <Clock size={14} aria-hidden /> Queued
        </span>
      );
    case 'RUNNING':
      return (
        <span className="inline-flex items-center gap-1 text-accent-text" role="status">
          <Loader2 size={14} className="animate-spin" aria-hidden /> Syncing since {timeAgo(run.started_at)}
        </span>
      );
    case 'SUCCEEDED':
      return (
        <span className="inline-flex items-center gap-1 text-success">
          <CheckCircle2 size={14} aria-hidden /> {run.chunk_count ?? 0} chunks
          <span className="text-fg-muted">· {timeAgo(run.finished_at)}</span>
        </span>
      );
    case 'FAILED':
      return (
        <span className="inline-flex items-center gap-1 text-danger">
          <XCircle size={14} aria-hidden /> Failed
          <span className="text-fg-muted">· {timeAgo(run.finished_at)}</span>
        </span>
      );
  }
}

function SkippedList({ skipped }: { skipped: SkippedFile[] }) {
  return (
    <details className="mt-1.5">
      <summary className="inline-flex cursor-pointer items-center gap-1.5 text-warning">
        <AlertTriangle size={14} aria-hidden /> {skipped.length} file{skipped.length === 1 ? '' : 's'} skipped
      </summary>
      <ul className="mt-1 ml-5 font-mono text-xs text-fg-muted space-y-0.5">
        {skipped.map((s) => (
          <li key={s.path}>
            {s.path}: {s.reason}
          </li>
        ))}
      </ul>
    </details>
  );
}

/** Replace an upload's files (`PUT …/upload`). The type stays the same; the source path may change. */
function ReplaceForm({
  courseId,
  resource,
  onDone,
}: {
  courseId: number;
  resource: Resource;
  onDone: () => Promise<void>;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [sourcePath, setSourcePath] = useState(resource.upload_source_path ?? '');
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);
  const [result, setResult] = useState<UploadResult | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const accept = resource.resource_type === 'QA_HISTORY' ? '' : UPLOAD_ACCEPT[resource.resource_type];

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!file) return;
    setSaving(true);
    setError('');
    try {
      const form = new FormData();
      form.append('file', file);
      form.append('source_path', sourcePath);
      setResult(await api.putForm<UploadResult>(`/courses/${courseId}/resources/${resource.id}/upload`, form));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to replace the file');
    } finally {
      setSaving(false);
    }
  }

  if (result) {
    return (
      <div className="mt-3 space-y-2">
        <UploadSummary files={result.files} skipped={result.skipped} />
        <Button size="sm" variant="outline" onClick={() => void onDone()}>
          Done
        </Button>
      </div>
    );
  }

  return (
    <form onSubmit={handleSubmit} className="mt-3 space-y-3 rounded-lg border border-border bg-surface-sunken p-3">
      <p className="text-xs text-fg-muted">
        Replacing moves lines and offsets, so citations posted earlier may highlight the wrong range. Their quoted
        text still shows what was cited.
      </p>
      <div className="flex flex-wrap items-end gap-3">
        <input
          ref={fileInput}
          type="file"
          accept={accept}
          onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          aria-label="Replacement file"
          className="text-sm text-fg-secondary file:mr-3 file:rounded-lg file:border file:border-border-strong file:bg-surface file:px-3 file:py-1.5 file:text-sm file:font-medium file:text-fg-secondary hover:file:bg-surface-hover"
          required
        />
        <Input
          value={sourcePath}
          onChange={(e) => setSourcePath(e.target.value)}
          aria-label="Source path"
          className="flex-1 min-w-48"
          required
        />
        <Button type="submit" size="sm" disabled={saving || !file}>
          {saving ? 'Uploading…' : 'Replace'}
        </Button>
      </div>
      {error && <p className="text-danger text-sm">{error}</p>}
    </form>
  );
}
