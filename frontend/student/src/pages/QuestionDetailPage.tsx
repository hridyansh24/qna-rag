import { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { ArrowLeft, Bot, CheckCircle2, Lock } from 'lucide-react';
import { api } from '../lib/api';
import { useCourse } from '../lib/CourseContext';
import type { QuestionDetail } from '../lib/types';
import { Button } from '../components/ui/button';
import { Card, CardContent } from '../components/ui/card';
import { Textarea } from '../components/ui/textarea';
import { Badge } from '../components/ui/badge';
import { Citations } from '../components/Citations';
import { RoleBadge } from '../components/RoleBadge';
import { useAiAnswerPolling } from '../lib/useAiAnswerPolling';
import { cn } from '../lib/utils';

export default function QuestionDetailPage() {
  const { courseId } = useCourse();
  const { questionId } = useParams();
  const [question, setQuestion] = useState<QuestionDetail | null>(null);
  const [kind, setKind] = useState<'ANSWER' | 'FOLLOWUP'>('FOLLOWUP');
  const [body, setBody] = useState('');
  const [error, setError] = useState('');
  const [posting, setPosting] = useState(false);

  async function load() {
    if (!courseId) return;
    const data = await api.get<QuestionDetail>(`/courses/${courseId}/questions/${questionId}`);
    setQuestion(data);
  }

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [courseId, questionId]);

  const ai = useAiAnswerPolling(question, load);

  async function handlePost(e: React.FormEvent) {
    e.preventDefault();
    if (!courseId) return;
    setPosting(true);
    setError('');
    try {
      const updated = await api.post<QuestionDetail>(
        `/courses/${courseId}/questions/${questionId}/posts`,
        { kind, body }
      );
      setQuestion(updated);
      setBody('');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to post');
    } finally {
      setPosting(false);
    }
  }

  if (!question) return <p className="p-8 text-fg-muted">Loading…</p>;

  return (
    <div className="p-8 max-w-2xl mx-auto space-y-6">
      <Link
        to="/questions"
        className="inline-flex items-center gap-1.5 text-sm text-fg-muted hover:text-fg"
      >
        <ArrowLeft size={16} /> Back to Questions
      </Link>
      <Card>
        <CardContent className="pt-6">
          <div className="flex items-start justify-between gap-4">
            <h2 className="text-xl font-bold text-fg">{question.title}</h2>
            <Badge variant={question.status === 'OPEN' ? 'success' : 'outline'}>
              {question.status}
            </Badge>
          </div>
          <p className="text-fg-muted text-sm mt-1">
            Asked by {question.author.display_name}
          </p>
          <p className="text-fg-secondary mt-4 whitespace-pre-wrap">{question.body}</p>
          <div className="flex gap-1.5 mt-4 flex-wrap">
            {question.categories.map((c) => (
              <Badge key={c.id}>{c.name}</Badge>
            ))}
          </div>
        </CardContent>
      </Card>

      <div className="space-y-3">
        {question.posts.map((post) => (
          <Card
            key={post.id}
            className={cn(post.author_role === 'AI' && 'border-l-4 border-l-ai', post.is_accepted && 'border-success')}
          >
            <CardContent className="pt-6">
              <div className="flex items-center justify-between gap-3 mb-2">
                <div className="flex items-center gap-2">
                  <span className="font-semibold text-fg">{post.author.display_name}</span>
                  <RoleBadge role={post.author_role} />
                  <Badge variant="outline">{post.kind === 'ANSWER' ? 'Answer' : 'Follow-up'}</Badge>
                </div>
                {post.is_accepted && (
                  <span className="flex items-center gap-1 text-success text-sm">
                    <CheckCircle2 size={16} /> Verified by staff
                  </span>
                )}
              </div>
              <p className="text-fg-secondary whitespace-pre-wrap">{post.body}</p>
              {post.author_role === 'AI' && <Citations citations={post.citations ?? []} />}
            </CardContent>
          </Card>
        ))}
        {ai.drafting && (
          <p className="flex items-center gap-2 text-sm text-fg-muted" role="status">
            <Bot size={16} className="animate-pulse" /> An AI answer is being drafted…
          </p>
        )}
        {ai.slow && (
          <p className="flex flex-wrap items-center gap-2 text-sm text-fg-muted" role="status">
            <Bot size={16} /> The AI answer is taking longer than usual.
            <Button size="sm" variant="outline" onClick={ai.checkAgain}>
              Check again
            </Button>
          </p>
        )}
      </div>

      {question.status === 'OPEN' ? (
        <Card>
          <CardContent className="pt-6">
            <form onSubmit={handlePost} className="space-y-3">
              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={() => setKind('FOLLOWUP')}
                  className={`rounded-lg px-3 py-1.5 text-sm border ${
                    kind === 'FOLLOWUP'
                      ? 'bg-accent border-accent text-on-accent'
                      : 'border-border-strong text-fg-secondary hover:bg-surface-hover'
                  }`}
                >
                  Follow-up
                </button>
                <button
                  type="button"
                  onClick={() => setKind('ANSWER')}
                  className={`rounded-lg px-3 py-1.5 text-sm border ${
                    kind === 'ANSWER'
                      ? 'bg-accent border-accent text-on-accent'
                      : 'border-border-strong text-fg-secondary hover:bg-surface-hover'
                  }`}
                >
                  Answer
                </button>
              </div>
              <Textarea
                placeholder={kind === 'ANSWER' ? 'Write an answer…' : 'Add a follow-up…'}
                value={body}
                onChange={(e) => setBody(e.target.value)}
                rows={4}
                required
              />
              {error && <p className="text-danger text-sm">{error}</p>}
              <Button type="submit" disabled={posting}>
                {posting ? 'Posting…' : 'Post'}
              </Button>
            </form>
          </CardContent>
        </Card>
      ) : (
        <p className="flex items-center gap-2 text-fg-muted text-sm">
          <Lock size={14} /> This thread was closed by course staff and no longer accepts new posts.
        </p>
      )}
    </div>
  );
}
