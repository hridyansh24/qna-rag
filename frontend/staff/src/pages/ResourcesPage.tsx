import { useCallback, useEffect, useMemo, useState } from 'react';
import { api } from '../lib/api';
import { useCourse } from '../lib/CourseContext';
import type { IngestionProfile, ProfilePreset, Resource } from '../lib/types';
import { AddResourceForm } from '../components/resources/AddResourceForm';
import { ProfilesSection } from '../components/resources/ProfilesSection';
import { ResourceCard, isActive } from '../components/resources/ResourceCard';
import { SettingsForm } from '../components/resources/SettingsForm';
import { Section } from '../components/resources/fields';

/** How often the resource list refreshes while any run is QUEUED or RUNNING. */
const POLL_MS = 3000;

/**
 * Staff management of the course's RAG sources (docs/design-rag.md §10,
 * step 8): resources and their sync status per profile, adding by URL or
 * upload, ingestion profiles, and the auto-responder settings.
 */
export default function ResourcesPage() {
  const { courseId } = useCourse();
  const [resources, setResources] = useState<Resource[] | null>(null);
  const [profiles, setProfiles] = useState<IngestionProfile[]>([]);
  const [presets, setPresets] = useState<ProfilePreset[]>([]);
  const [error, setError] = useState('');

  const loadResources = useCallback(async () => {
    if (!courseId) return;
    try {
      setResources(await api.get<Resource[]>(`/courses/${courseId}/resources`));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load resources');
    }
  }, [courseId]);

  const loadAll = useCallback(async () => {
    if (!courseId) return;
    const [p] = await Promise.all([
      api.get<IngestionProfile[]>(`/courses/${courseId}/profiles`),
      loadResources(),
    ]);
    setProfiles(p);
  }, [courseId, loadResources]);

  useEffect(() => {
    if (!courseId) return;
    setResources(null);
    setError('');
    loadAll().catch((err) => setError(err instanceof Error ? err.message : 'Failed to load'));
    api.get<ProfilePreset[]>(`/courses/${courseId}/profiles/presets`).then(setPresets).catch(() => setPresets([]));
  }, [courseId, loadAll]);

  const activeProfiles = useMemo(() => {
    const names = new Set<string>();
    for (const r of resources ?? []) {
      for (const [name, run] of Object.entries(r.latest_runs)) if (isActive(run)) names.add(name);
    }
    return names;
  }, [resources]);

  // Poll while anything is syncing; each response decides whether to keep going.
  useEffect(() => {
    if (activeProfiles.size === 0) return;
    const timer = window.setTimeout(() => void loadResources(), POLL_MS);
    return () => window.clearTimeout(timer);
  }, [activeProfiles, resources, loadResources]);

  if (!courseId) return <p className="p-8 text-fg-muted">You aren't staff in any course yet.</p>;

  const profileNames = profiles.map((p) => p.name);

  return (
    <div className="p-8 max-w-3xl mx-auto space-y-10">
      <div>
        <h2 className="text-2xl font-bold text-fg">Resources</h2>
        <p className="mt-1 text-fg-muted">
          The course materials the AI assistant answers from. Add a source, then sync it into a profile to index it.
        </p>
      </div>

      {error && <p className="text-danger text-sm">{error}</p>}

      <Section
        title="Sources"
        description={
          activeProfiles.size > 0 ? (
            <span role="status">Syncing… this list refreshes every few seconds.</span>
          ) : (
            'Each row shows the latest sync in every profile.'
          )
        }
      >
        {resources === null ? (
          <p className="text-fg-muted">Loading…</p>
        ) : (
          <div className="space-y-3">
            {resources.map((r) => (
              <ResourceCard
                key={r.id}
                courseId={courseId}
                resource={r}
                profiles={profileNames}
                onChange={loadResources}
              />
            ))}
          </div>
        )}
      </Section>

      <Section title="Add a source" description="Register a URL, which the app fetches on every sync. Upload a file only when the source isn't reachable by URL.">
        <AddResourceForm courseId={courseId} onAdded={loadResources} />
      </Section>

      <ProfilesSection
        courseId={courseId}
        profiles={profiles}
        presets={presets}
        activeProfiles={activeProfiles}
        onChange={loadAll}
      />

      <Section title="Auto-responder" description="How new questions in this course are answered.">
        <SettingsForm courseId={courseId} profiles={profiles} />
      </Section>
    </div>
  );
}
