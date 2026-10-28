import { useState } from 'react';
import { Layers, Plus, RefreshCw } from 'lucide-react';
import { api } from '../../lib/api';
import type { IngestionProfile, ProfilePreset } from '../../lib/types';
import { Badge } from '../ui/badge';
import { Button } from '../ui/button';
import { Card } from '../ui/card';
import { Input } from '../ui/input';
import { Textarea } from '../ui/textarea';
import { Field, Section } from './fields';

/**
 * Ingestion profiles (§7.4). Profiles are immutable, so there is no edit or
 * delete: staff create one from a preset (or a custom chunking config) and
 * sync every resource into it.
 */
export function ProfilesSection({
  courseId,
  profiles,
  presets,
  activeProfiles,
  onChange,
}: {
  courseId: number;
  profiles: IngestionProfile[];
  presets: ProfilePreset[];
  /** Profiles with a QUEUED or RUNNING run on any resource. */
  activeProfiles: Set<string>;
  onChange: () => Promise<void>;
}) {
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState('');
  const missingPresets = presets.filter((p) => !profiles.some((q) => q.name === p.name));

  async function run(key: string, action: () => Promise<unknown>) {
    setBusy(key);
    setError('');
    try {
      await action();
      await onChange();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Request failed');
    } finally {
      setBusy(null);
    }
  }

  const createProfile = (body: ProfilePreset) =>
    run(`create:${body.name}`, () => api.post(`/courses/${courseId}/profiles`, body));

  return (
    <Section
      title="Ingestion profiles"
      description="Each profile is its own embedding model and chunking, with its own index. Profiles can't be edited once created."
    >
      {error && <p className="text-danger text-sm">{error}</p>}

      {profiles.length === 0 && (
        <p className="text-sm text-fg-muted">No profiles yet. Create one from a preset below.</p>
      )}

      <div className="space-y-2">
        {profiles.map((p) => (
          <Card key={p.name} className="px-5 py-4">
            <div className="flex items-start justify-between gap-4">
              <div className="min-w-0">
                <p className="flex items-center gap-2 font-semibold text-fg">
                  <Layers size={16} className="shrink-0 text-accent-text" aria-hidden /> {p.name}
                </p>
                <p className="mt-1 text-sm text-fg-muted break-all">{p.embedding_model}</p>
                <p className="mt-1.5 flex flex-wrap gap-1.5">
                  {Object.entries(p.chunking).map(([type, cfg]) => (
                    <Badge key={type} variant="outline" className="font-mono">
                      {type}: {describeChunker(cfg)}
                    </Badge>
                  ))}
                </p>
              </div>
              <Button
                size="sm"
                variant="outline"
                disabled={busy !== null || activeProfiles.has(p.name)}
                onClick={() =>
                  run(`sync:${p.name}`, () => api.post(`/courses/${courseId}/profiles/${p.name}/sync-all`))
                }
                title={activeProfiles.has(p.name) ? 'A sync is already running for this profile' : undefined}
              >
                <RefreshCw
                  size={14}
                  className={`mr-1.5 ${activeProfiles.has(p.name) ? 'animate-spin' : ''}`}
                  aria-hidden
                />
                {activeProfiles.has(p.name) ? 'Syncing…' : 'Sync all'}
              </Button>
            </div>
          </Card>
        ))}
      </div>

      {missingPresets.length > 0 && (
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-sm text-fg-muted">Create from preset:</span>
          {missingPresets.map((p) => (
            <Button
              key={p.name}
              size="sm"
              variant="outline"
              disabled={busy !== null}
              onClick={() => createProfile(p)}
            >
              <Plus size={14} className="mr-1" aria-hidden /> {p.name}
            </Button>
          ))}
        </div>
      )}

      <CustomProfileForm
        template={presets[0]}
        busy={busy !== null}
        onCreate={(body) => createProfile(body)}
      />
    </Section>
  );
}

/** "sliding_window 200/40" or "semantic p25 ≤220". */
function describeChunker(cfg: Record<string, unknown>): string {
  if (cfg.strategy === 'semantic') return `semantic p${cfg.breakpoint_percentile} ≤${cfg.max_tokens}`;
  return `${cfg.strategy} ${cfg.chunk_size}/${cfg.chunk_overlap}`;
}

function CustomProfileForm({
  template,
  busy,
  onCreate,
}: {
  template: ProfilePreset | undefined;
  busy: boolean;
  onCreate: (body: ProfilePreset) => Promise<void>;
}) {
  const [name, setName] = useState('');
  const [model, setModel] = useState(template?.embedding_model ?? '');
  const [chunking, setChunking] = useState(template ? JSON.stringify(template.chunking, null, 2) : '');
  const [error, setError] = useState('');

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    let parsed: ProfilePreset['chunking'];
    try {
      parsed = JSON.parse(chunking);
    } catch {
      setError('Chunking must be valid JSON.');
      return;
    }
    setError('');
    await onCreate({ name, embedding_model: model, chunking: parsed });
  }

  return (
    <details className="group rounded-xl border border-border bg-surface px-5 py-3">
      <summary className="cursor-pointer text-sm font-medium text-fg-secondary">Custom profile</summary>
      <form onSubmit={handleSubmit} className="mt-4 space-y-3">
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Name" hint="Lowercase letters, digits and dashes.">
            <Input value={name} onChange={(e) => setName(e.target.value)} pattern="[a-z0-9][a-z0-9-]{0,38}[a-z0-9]" required />
          </Field>
          <Field label="Embedding model" hint="Must be served by Infinity.">
            <Input value={model} onChange={(e) => setModel(e.target.value)} required />
          </Field>
        </div>
        <Field label="Chunking (JSON)" hint="A default chunker, plus optional pdf, web and markdown overrides. Token counts are at most 250.">
          <Textarea
            value={chunking}
            onChange={(e) => setChunking(e.target.value)}
            rows={8}
            className="font-mono text-sm"
            required
          />
        </Field>
        {error && <p className="text-danger text-sm">{error}</p>}
        <Button type="submit" size="sm" disabled={busy}>
          Create profile
        </Button>
      </form>
    </details>
  );
}
