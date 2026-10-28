import { useEffect, useMemo, useRef, useState } from 'react';
import { Link, useParams, useSearchParams } from 'react-router-dom';
import { ArrowLeft } from 'lucide-react';
import { api } from '../lib/api';
import { useCourse } from '../lib/CourseContext';
import { Card, CardContent } from '../components/ui/card';

/**
 * Shows an uploaded course file that an AI answer cites (docs/design-rag.md
 * §5.5). Route: sources/:resourceId/<source path>?lines=a-b | ?chars=a-b |
 * ?page=n | ?q=text.
 *
 * Uploaded files are served by a member-only API endpoint that needs the
 * Bearer token, so a plain link can't open them. This page fetches the file
 * through api.ts and then shows markdown and HTML as numbered plain-text
 * lines (never rendered as a page) with the cited range highlighted, or a
 * PDF opened at the cited page. HTML is fetched as its document text
 * (`?format=text`), the text ingestion's `?chars=` offsets index into.
 */
export default function SourceViewerPage() {
  const { courseId } = useCourse();
  const { resourceId, '*': sourcePath = '' } = useParams();
  const [params] = useSearchParams();
  const [text, setText] = useState<string | null>(null);
  const [pdfUrl, setPdfUrl] = useState<string | null>(null);
  const [error, setError] = useState('');
  const firstHighlight = useRef<HTMLLIElement | null>(null);

  const isPdf = sourcePath.toLowerCase().endsWith('.pdf');
  const isHtml = /\.html?$/i.test(sourcePath);
  const page = params.get('page');

  useEffect(() => {
    if (!courseId || !resourceId) return;
    let objectUrl: string | null = null;
    const encoded = sourcePath.split('/').map(encodeURIComponent).join('/');
    const format = isHtml ? '?format=text' : '';
    setText(null);
    setPdfUrl(null);
    setError('');
    api
      .getBlob(`/courses/${courseId}/resources/${resourceId}/files/${encoded}${format}`)
      .then(async (blob) => {
        if (isPdf) {
          objectUrl = URL.createObjectURL(new Blob([blob], { type: 'application/pdf' }));
          setPdfUrl(objectUrl);
        } else {
          setText(await blob.text());
        }
      })
      .catch((err) => setError(err instanceof Error ? err.message : 'Failed to load the file'));
    return () => {
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [courseId, resourceId, sourcePath, isPdf, isHtml]);

  const lines = useMemo(() => (text === null ? [] : text.split('\n')), [text]);
  const lineStarts = useMemo(() => codePointLineStarts(lines), [lines]);
  const charRange = useMemo(() => parseRange(params.get('chars')), [params]);
  const highlighted = useMemo(
    () =>
      charRange
        ? linesInCharRange(lines, lineStarts, charRange)
        : highlightedLines(lines, params.get('lines'), params.get('q')),
    [lines, lineStarts, charRange, params]
  );

  useEffect(() => {
    firstHighlight.current?.scrollIntoView({ block: 'center' });
  }, [highlighted]);

  const firstHighlightedLine = Math.min(...highlighted);

  return (
    <div className="p-8 max-w-4xl mx-auto space-y-4">
      <Link
        to="/questions"
        className="inline-flex items-center gap-1.5 text-sm text-fg-muted hover:text-fg"
      >
        <ArrowLeft size={16} /> Back to Questions
      </Link>
      <h2 className="text-lg font-semibold text-fg break-all">{sourcePath}</h2>
      {error && <p className="text-danger text-sm">{error}</p>}

      {pdfUrl && page && (
        // Shown in case the browser's PDF viewer ignores the #page fragment (§5.5).
        <p className="text-sm text-fg-secondary">
          Cited: <span className="font-semibold text-fg">page {page}</span>
        </p>
      )}
      {pdfUrl && (
        <iframe
          title={sourcePath}
          src={page ? `${pdfUrl}#page=${encodeURIComponent(page)}` : pdfUrl}
          className="w-full h-[75vh] rounded-lg border border-border bg-surface"
        />
      )}

      {text !== null && (
        <Card>
          <CardContent className="pt-6 overflow-x-auto">
            <ol className="font-mono text-sm">
              {lines.map((line, i) => {
                const n = i + 1;
                const on = highlighted.has(n);
                return (
                  <li
                    key={n}
                    ref={on && n === firstHighlightedLine ? firstHighlight : undefined}
                    className={`flex gap-4 whitespace-pre-wrap ${on && !charRange ? 'bg-highlight/50' : ''}`}
                  >
                    <span className="w-10 shrink-0 text-right text-fg-muted select-none">{n}</span>
                    <span className="text-fg-secondary">
                      {on && charRange ? markCharRange(line, lineStarts[i], charRange) : line || ' '}
                    </span>
                  </li>
                );
              })}
            </ol>
          </CardContent>
        </Card>
      )}

      {!error && text === null && !pdfUrl && <p className="text-fg-muted">Loading…</p>}
    </div>
  );
}

/** "a-b" or "a" as [a, b]; null when absent or malformed. */
function parseRange(range: string | null): [number, number] | null {
  const match = range?.match(/^(\d+)(?:-(\d+))?$/);
  return match ? [Number(match[1]), Number(match[2] ?? match[1])] : null;
}

/**
 * Each line's starting offset in code points. The backend's char offsets
 * are Python string indexes (code points), not JS UTF-16 indexes, so they
 * only agree when counted this way.
 */
function codePointLineStarts(lines: string[]): number[] {
  const starts: number[] = [];
  let offset = 0;
  for (const line of lines) {
    starts.push(offset);
    offset += Array.from(line).length + 1; // + the '\n'
  }
  return starts;
}

/** 1-based line numbers overlapping the half-open code-point range [a, b). */
function linesInCharRange(
  lines: string[],
  starts: number[],
  [a, b]: [number, number]
): Set<number> {
  const out = new Set<number>();
  lines.forEach((line, i) => {
    const end = starts[i] + Array.from(line).length + 1;
    if (starts[i] < b && end > a) out.add(i + 1);
  });
  return out;
}

/** The line with the part inside [a, b) wrapped in a highlight. */
function markCharRange(line: string, start: number, [a, b]: [number, number]) {
  const chars = Array.from(line);
  const from = Math.max(a - start, 0);
  const to = Math.min(b - start, chars.length);
  if (to <= from) return line || ' ';
  return (
    <>
      {chars.slice(0, from).join('')}
      <mark className="bg-highlight text-fg rounded-sm">{chars.slice(from, to).join('')}</mark>
      {chars.slice(to).join('')}
    </>
  );
}

/** 1-based line numbers to highlight, from ?lines=a-b, or the first line containing ?q=. */
function highlightedLines(lines: string[], range: string | null, query: string | null): Set<number> {
  const parsed = parseRange(range);
  if (parsed) {
    const [start, end] = parsed;
    const out = new Set<number>();
    for (let n = start; n <= Math.min(end, lines.length); n++) out.add(n);
    return out;
  }
  if (query) {
    const needle = query.toLowerCase();
    const index = lines.findIndex((l) => l.toLowerCase().includes(needle));
    if (index >= 0) return new Set([index + 1]);
  }
  return new Set();
}
