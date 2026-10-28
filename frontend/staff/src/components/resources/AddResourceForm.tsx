import { useRef, useState } from 'react';
import { Link2, Upload } from 'lucide-react';
import { api } from '../../lib/api';
import type { Resource, ResourceType, SkippedFile, UploadResult } from '../../lib/types';
import { Button } from '../ui/button';
import { Card, CardContent } from '../ui/card';
import { Input } from '../ui/input';
import { cn } from '../../lib/utils';
import { Field, selectClass } from './fields';

type AddableType = Exclude<ResourceType, 'QA_HISTORY'>;

const TYPE_LABELS: Record<AddableType, string> = {
  SYLLABUS: 'Syllabus',
  SCHEDULE: 'Schedule',
  REPOSITORY: 'Repository',
};

/** What each type accepts (§9.5, "Validation by resource type"). */
export const UPLOAD_ACCEPT: Record<AddableType, string> = {
  SYLLABUS: '.html,.htm',
  SCHEDULE: '.html,.htm',
  REPOSITORY: '.zip,.md,.pdf',
};

const URL_HINTS: Record<AddableType, string> = {
  SYLLABUS: 'The public syllabus page. The app fetches it on every sync.',
  SCHEDULE: 'The public schedule page. The app fetches it on every sync.',
  REPOSITORY: 'An https GitLab clone URL. The app shallow-clones it with the server’s token.',
};

const SOURCE_PATH_HINTS: Record<AddableType, string> = {
  SYLLABUS: 'The file\u2019s path in the course repository, e.g. eval/sample_data/web/syllabus.html. It must end in the file\u2019s extension.',
  SCHEDULE: 'The file\u2019s path in the course repository, e.g. eval/sample_data/web/schedule.html. It must end in the file\u2019s extension.',
  REPOSITORY:
    'For a zip, the folder it came from, e.g. eval/sample_data/repo/ (a top folder of the same name is stripped). For one .md or .pdf, the file\u2019s full path.',
};

/**
 * Register a resource by URL (the primary path, T4) or by upload (the
 * fallback for a source that isn't reachable by URL).
 */
export function AddResourceForm({
  courseId,
  onAdded,
}: {
  courseId: number;
  onAdded: (resource: Resource) => Promise<void>;
}) {
  const [mode, setMode] = useState<'url' | 'upload'>('url');
  const [type, setType] = useState<AddableType>('SYLLABUS');
  const [name, setName] = useState('');
  const [url, setUrl] = useState('');
  const [repoRef, setRepoRef] = useState('');
  const [sourcePath, setSourcePath] = useState('');
  const [file, setFile] = useState<File | null>(null);
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);
  const [uploaded, setUploaded] = useState<{ files: string[]; skipped: SkippedFile[] } | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  function reset() {
    setName('');
    setUrl('');
    setRepoRef('');
    setSourcePath('');
    setFile(null);
    if (fileInput.current) fileInput.current.value = '';
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError('');
    setUploaded(null);
    try {
      let resource: Resource;
      if (mode === 'url') {
        resource = await api.post<Resource>(`/courses/${courseId}/resources`, {
          resource_type: type,
          display_name: name,
          url,
          ...(type === 'REPOSITORY' && repoRef ? { repo_ref: repoRef } : {}),
        });
      } else {
        if (!file) throw new Error('Choose a file to upload.');
        const form = new FormData();
        form.append('file', file);
        form.append('resource_type', type);
        form.append('display_name', name);
        form.append('source_path', sourcePath);
        const result = await api.postForm<UploadResult>(`/courses/${courseId}/resources/upload`, form);
        setUploaded({ files: result.files, skipped: result.skipped });
        resource = result;
      }
      reset();
      await onAdded(resource);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to add the resource');
    } finally {
      setSaving(false);
    }
  }

  const tabClass = (active: boolean) =>
    cn(
      'inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium transition-colors',
      active ? 'bg-surface text-fg shadow-sm' : 'text-fg-muted hover:text-fg'
    );

  return (
    <Card>
      <CardContent className="pt-6 space-y-4">
        <div className="inline-flex rounded-lg bg-surface-hover p-1" role="tablist" aria-label="How to add">
          <button type="button" role="tab" aria-selected={mode === 'url'} className={tabClass(mode === 'url')} onClick={() => setMode('url')}>
            <Link2 size={14} aria-hidden /> By URL
          </button>
          <button type="button" role="tab" aria-selected={mode === 'upload'} className={tabClass(mode === 'upload')} onClick={() => setMode('upload')}>
            <Upload size={14} aria-hidden /> Upload a file
          </button>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Type">
              <select value={type} onChange={(e) => setType(e.target.value as AddableType)} className={selectClass}>
                {(Object.keys(TYPE_LABELS) as AddableType[]).map((t) => (
                  <option key={t} value={t}>
                    {TYPE_LABELS[t]}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Display name" hint="Shown on citations, e.g. “Syllabus”.">
              <Input value={name} onChange={(e) => setName(e.target.value)} maxLength={255} required />
            </Field>
          </div>

          {mode === 'url' ? (
            <div className="grid gap-4 sm:grid-cols-3">
              <Field label="URL" hint={URL_HINTS[type]} className="sm:col-span-2">
                <Input type="url" value={url} onChange={(e) => setUrl(e.target.value)} maxLength={2048} placeholder="https://…" required />
              </Field>
              {type === 'REPOSITORY' && (
                <Field label="Branch or tag" hint="Optional. Defaults to the repository's default branch.">
                  <Input value={repoRef} onChange={(e) => setRepoRef(e.target.value)} maxLength={255} placeholder="main" />
                </Field>
              )}
            </div>
          ) : (
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="File" hint={`Accepts ${UPLOAD_ACCEPT[type].split(',').join(', ')}.`}>
                <input
                  ref={fileInput}
                  type="file"
                  accept={UPLOAD_ACCEPT[type]}
                  onChange={(e) => setFile(e.target.files?.[0] ?? null)}
                  className="block w-full text-sm text-fg-secondary file:mr-3 file:rounded-lg file:border file:border-border-strong file:bg-surface file:px-3 file:py-1.5 file:text-sm file:font-medium file:text-fg-secondary hover:file:bg-surface-hover"
                  required
                />
              </Field>
              <Field label="Source path" hint={SOURCE_PATH_HINTS[type]}>
                <Input value={sourcePath} onChange={(e) => setSourcePath(e.target.value)} required />
              </Field>
            </div>
          )}

          {error && <p className="text-danger text-sm">{error}</p>}
          <Button type="submit" disabled={saving}>
            {saving ? 'Adding…' : mode === 'url' ? 'Register URL' : 'Upload'}
          </Button>
        </form>

        {uploaded && <UploadSummary files={uploaded.files} skipped={uploaded.skipped} />}
      </CardContent>
    </Card>
  );
}

/** The stored paths and the skipped entries an upload returned. */
export function UploadSummary({ files, skipped }: { files: string[]; skipped: SkippedFile[] }) {
  return (
    <div className="rounded-lg border border-border bg-surface-sunken p-3 text-sm" role="status">
      <p className="text-fg-secondary">
        Stored {files.length} file{files.length === 1 ? '' : 's'}
        {skipped.length > 0 && `, skipped ${skipped.length}`}. Sync a profile to index them.
      </p>
      <ul className="mt-2 max-h-40 overflow-auto font-mono text-xs text-fg-muted space-y-0.5">
        {files.map((f) => (
          <li key={f}>{f}</li>
        ))}
        {skipped.map((s) => (
          <li key={s.path} className="text-warning">
            {s.path}: {s.reason}
          </li>
        ))}
      </ul>
    </div>
  );
}
