import { useEffect, useState } from 'react';
import { api } from '../../lib/api';
import type { IngestionProfile, RagSettings } from '../../lib/types';
import { Button } from '../ui/button';
import { Card, CardContent } from '../ui/card';
import { Input } from '../ui/input';
import { Textarea } from '../ui/textarea';
import { Field, selectClass } from './fields';

/**
 * The course's auto-responder settings (§9.5). PUT replaces every field;
 * the backend rejects a profile this course doesn't have, or a model that
 * isn't pulled into Ollama, with the reason in the error message.
 */
export function SettingsForm({
  courseId,
  profiles,
}: {
  courseId: number;
  profiles: IngestionProfile[];
}) {
  const [form, setForm] = useState<RagSettings | null>(null);
  const [error, setError] = useState('');
  const [saved, setSaved] = useState(false);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    api
      .get<RagSettings>(`/courses/${courseId}/rag/settings`)
      .then(setForm)
      .catch((err) => setError(err instanceof Error ? err.message : 'Failed to load settings'));
  }, [courseId]);

  if (!form) {
    return error ? <p className="text-danger text-sm">{error}</p> : <p className="text-fg-muted">Loading…</p>;
  }

  function update<K extends keyof RagSettings>(key: K, value: RagSettings[K]) {
    setForm((f) => (f ? { ...f, [key]: value } : f));
    setSaved(false);
  }

  async function handleSave(e: React.FormEvent) {
    e.preventDefault();
    if (!form) return;
    setSaving(true);
    setError('');
    try {
      setForm(await api.put<RagSettings>(`/courses/${courseId}/rag/settings`, form));
      setSaved(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to save settings');
    } finally {
      setSaving(false);
    }
  }

  const activeMissing = !profiles.some((p) => p.name === form.active_profile);

  return (
    <Card>
      <CardContent className="pt-6">
        <form onSubmit={handleSave} className="space-y-4">
          <label className="flex items-center gap-3">
            <input
              type="checkbox"
              checked={form.enabled}
              onChange={(e) => update('enabled', e.target.checked)}
              className="h-4 w-4 accent-accent"
            />
            <span className="text-fg font-medium">Answer new questions automatically</span>
          </label>

          <div className="grid gap-4 sm:grid-cols-3">
            <Field
              label="Active profile"
              hint={activeMissing ? 'Not created yet. Create it below, then sync it.' : 'Retrieval uses this collection.'}
            >
              <select
                value={form.active_profile}
                onChange={(e) => update('active_profile', e.target.value)}
                className={selectClass}
              >
                {activeMissing && <option value={form.active_profile}>{form.active_profile} (not created)</option>}
                {profiles.map((p) => (
                  <option key={p.name} value={p.name}>
                    {p.name}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Similarity threshold" hint="0–1. Chunks below it are never used.">
              <Input
                type="number"
                min={0}
                max={1}
                step={0.01}
                value={form.similarity_threshold}
                onChange={(e) => update('similarity_threshold', Number(e.target.value))}
                required
              />
            </Field>
            <Field label="Generation model" hint="Must be pulled into Ollama.">
              <Input
                value={form.generation_model}
                onChange={(e) => update('generation_model', e.target.value)}
                required
              />
            </Field>
          </div>

          <Field label="System prompt">
            <Textarea
              value={form.system_prompt}
              onChange={(e) => update('system_prompt', e.target.value)}
              rows={6}
              className="font-mono text-sm"
              required
            />
          </Field>

          {error && <p className="text-danger text-sm">{error}</p>}
          <div className="flex items-center gap-3">
            <Button type="submit" disabled={saving}>
              {saving ? 'Saving…' : 'Save settings'}
            </Button>
            {saved && (
              <span className="text-sm text-success" role="status">
                Saved
              </span>
            )}
          </div>
        </form>
      </CardContent>
    </Card>
  );
}
