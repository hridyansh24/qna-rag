import { useEffect, useRef, useState } from 'react';
import type { QuestionDetail } from './types';

const FAST_MS = 3_000;
const SLOW_MS = 10_000;
const FAST_FOR_MS = 60_000;
const GIVE_UP_AFTER_MS = 5 * 60_000;

export interface AiAnswerPolling {
  /** Show "An AI answer is being drafted…". */
  drafting: boolean;
  /** Still PENDING after 5 minutes: polling stopped, show "Check again". */
  slow: boolean;
  /** Fetch once, and poll for another 5 minutes if still PENDING. */
  checkAgain: () => void;
}

/**
 * While the auto-responder is still working on a question
 * (ai_status === 'PENDING'), re-fetch the thread so the AI answer appears
 * without a manual refresh: every 3s for the first minute, then every 10s,
 * and stop after 5 minutes, since generations queue one at a time on the
 * server (docs/design-rag.md §10). After that, `slow` is true until
 * `checkAgain` finds the answer or restarts the polling.
 *
 * `question` is the latest loaded thread; each reload produces a new object,
 * which schedules the next poll.
 */
export function useAiAnswerPolling(
  question: QuestionDetail | null,
  reload: () => Promise<void>
): AiAnswerPolling {
  const startedAt = useRef<number | null>(null);
  const polledId = useRef<number | undefined>(undefined);
  const reloadRef = useRef(reload);
  reloadRef.current = reload;
  const [gaveUp, setGaveUp] = useState(false);

  const pending = question?.ai_status === 'PENDING';

  useEffect(() => {
    if (polledId.current !== question?.id) {
      // A different thread: its 5 minutes start now.
      polledId.current = question?.id;
      startedAt.current = null;
      setGaveUp(false);
    }
    if (!pending) {
      startedAt.current = null;
      setGaveUp(false);
      return;
    }
    startedAt.current ??= Date.now();
    const elapsed = Date.now() - startedAt.current;
    if (elapsed >= GIVE_UP_AFTER_MS) {
      setGaveUp(true);
      return;
    }
    const timer = setTimeout(
      () => void reloadRef.current().catch(() => undefined),
      elapsed < FAST_FOR_MS ? FAST_MS : SLOW_MS
    );
    return () => clearTimeout(timer);
  }, [pending, question]);

  function checkAgain() {
    // The reload yields a new question object; if it is still PENDING, the
    // effect above starts a fresh 5-minute window.
    startedAt.current = null;
    setGaveUp(false);
    // A failed fetch goes back to "taking longer", not to a notice that never updates.
    void reloadRef.current().catch(() => setGaveUp(true));
  }

  return { drafting: pending && !gaveUp, slow: pending && gaveUp, checkAgain };
}
