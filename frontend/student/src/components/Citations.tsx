import { Link } from 'react-router-dom';
import { ExternalLink, FileText } from 'lucide-react';
import type { Citation } from '../lib/types';

/**
 * The sources an AI answer was grounded in (docs/design-rag.md §6.4, §10),
 * ranked by similarity; rank 1 is "the source". Citation URLs come in three
 * kinds:
 *  - external http(s) links (syllabus Text Fragments, GitLab blob/raw links)
 *    open in a new tab;
 *  - app paths like "/student/questions/7" are rewritten to this app's own
 *    routes, so the same stored citation works in the student and staff apps;
 *  - viewer paths like "sources/12/…?lines=10-25" go to the in-app source
 *    viewer for uploaded files.
 * Anything else is shown as plain text: stored data never becomes a
 * javascript: or other non-http link.
 */
export function Citations({ citations }: { citations: Citation[] }) {
  if (citations.length === 0) return null;
  const sorted = [...citations].sort((a, b) => a.rank - b.rank);

  return (
    <div className="mt-4 border-t border-border pt-3">
      <p className="text-xs font-semibold uppercase tracking-wide text-fg-muted mb-2">
        {sorted.length === 1 ? 'Source' : 'Sources'}
      </p>
      <ol className="space-y-2">
        {sorted.map((c) => (
          <li key={c.rank} className="text-sm">
            <div className="flex items-start gap-1.5">
              <span className="text-fg-muted shrink-0">[{c.rank}]</span>
              <CitationLink citation={c} />
            </div>
            {c.quoted_text && (
              <blockquote className="mt-1 ml-6 border-l-2 border-border-strong pl-2 text-fg-muted line-clamp-3 whitespace-pre-wrap">
                {c.quoted_text}
              </blockquote>
            )}
          </li>
        ))}
      </ol>
    </div>
  );
}

function CitationLink({ citation }: { citation: Citation }) {
  const target = resolveCitationUrl(citation.citation_url);
  const linkClass = 'inline-flex items-center gap-1 text-accent-text underline decoration-accent-text/40 underline-offset-2 hover:decoration-accent-text';

  if (target.kind === 'external') {
    return (
      <a href={target.href} target="_blank" rel="noopener noreferrer" className={linkClass}>
        {citation.label} <ExternalLink size={12} aria-hidden />
        <span className="sr-only">(opens in a new tab)</span>
      </a>
    );
  }
  if (target.kind === 'internal') {
    return (
      <Link to={target.to} className={linkClass}>
        <FileText size={12} aria-hidden /> {citation.label}
      </Link>
    );
  }
  return <span className="text-fg-secondary">{citation.label}</span>;
}

type ResolvedUrl =
  | { kind: 'external'; href: string }
  | { kind: 'internal'; to: string }
  | { kind: 'none' };

export function resolveCitationUrl(url: string): ResolvedUrl {
  if (/^https?:\/\//i.test(url)) return { kind: 'external', href: url };
  const appPath = url.match(/^\/(?:student|staff)(\/.*)$/);
  if (appPath) return { kind: 'internal', to: appPath[1] };
  if (/^\/?sources\//.test(url)) return { kind: 'internal', to: `/${url.replace(/^\//, '')}` };
  return { kind: 'none' };
}
