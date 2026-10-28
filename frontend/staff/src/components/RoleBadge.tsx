import { Bot } from 'lucide-react';
import { Badge } from './ui/badge';
import type { AuthorRole } from '../lib/types';

/**
 * The author badge on a post. AI answers get their own clearly different
 * label (T5: "clearly labeled as AI-generated"); before 'AI' existed, any
 * non-staff role rendered as "Student".
 */
export function RoleBadge({ role }: { role: AuthorRole }) {
  if (role === 'AI') {
    return (
      <Badge variant="ai" className="gap-1">
        <Bot size={12} aria-hidden /> AI-generated
      </Badge>
    );
  }
  if (role === 'STAFF') return <Badge variant="default">Course Staff</Badge>;
  return <Badge variant="outline">Student</Badge>;
}
