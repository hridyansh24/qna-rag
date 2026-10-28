export interface MyCourse {
  id: number;
  name: string;
  semester: string;
  role: 'STUDENT' | 'STAFF';
}

export interface Category {
  id: number;
  course_id: number;
  name: string;
  description: string;
  created_at: string;
}

export interface AuthorSummary {
  id: string;
  display_name: string;
}

export interface QuestionSummary {
  id: number;
  course_id: number;
  title: string;
  status: 'OPEN' | 'CLOSED';
  author: AuthorSummary;
  categories: Category[];
  post_count: number;
  has_accepted_answer: boolean;
  /** True when the thread has a (non-hidden) AI-generated answer. */
  has_ai_answer?: boolean;
  created_at: string;
  updated_at: string;
}

/** 'AI' marks an answer posted by the auto-responder (docs/design-rag.md §6). */
export type AuthorRole = 'STUDENT' | 'STAFF' | 'AI';

/**
 * Where the auto-responder is for a question. Only PENDING changes what the
 * UI shows; every other final state looks like an ordinary unanswered
 * question (§10).
 */
export type AiStatus =
  | 'NONE'
  | 'PENDING'
  | 'ANSWERED'
  | 'NO_MATCH'
  | 'DECLINED'
  | 'DISABLED'
  | 'NOT_READY'
  | 'SKIPPED'
  | 'FAILED';

/**
 * One source an AI answer was grounded in, copied from retrieval (§4.1, §5);
 * CitationResponse in §9.6. It has no id: `rank` (1–4) is unique per post.
 */
export interface Citation {
  rank: number;
  /** Null once the cited resource has been deleted; the copied fields still show. */
  resource_id: number | null;
  resource_type: 'syllabus' | 'schedule' | 'repo_markdown' | 'repo_pdf' | 'qa_thread';
  label: string;
  /**
   * An external URL (Text Fragment or GitLab link), an app path such as
   * "/student/questions/7", or a viewer path such as "sources/12/…?lines=10-25".
   */
  citation_url: string;
  /** Where in the source: line range, page, character offsets or thread (§4.1). */
  location: Record<string, unknown>;
  quoted_text: string;
  similarity_score: number;
}

export interface Post {
  id: number;
  question_id: number;
  author: AuthorSummary;
  author_role: AuthorRole;
  kind: 'ANSWER' | 'FOLLOWUP';
  body: string;
  is_accepted: boolean;
  accepted_by: AuthorSummary | null;
  accepted_at: string | null;
  created_at: string;
  citations?: Citation[];
  is_hidden?: boolean;
}

export interface QuestionDetail {
  id: number;
  course_id: number;
  title: string;
  body: string;
  status: 'OPEN' | 'CLOSED';
  author: AuthorSummary;
  categories: Category[];
  posts: Post[];
  closed_by: AuthorSummary | null;
  closed_at: string | null;
  ai_status?: AiStatus;
  created_at: string;
  updated_at: string;
}

// ---------------------------------------------------------------------------
// Resources, ingestion profiles and runs (docs/design-rag.md §9.5, §9.6)
// ---------------------------------------------------------------------------

export type ResourceType = 'SYLLABUS' | 'SCHEDULE' | 'REPOSITORY' | 'QA_HISTORY';
export type RunStatus = 'QUEUED' | 'RUNNING' | 'SUCCEEDED' | 'FAILED';

export interface SkippedFile {
  path: string;
  reason: string;
}

export interface IngestionRun {
  id: number;
  resource_id: number;
  profile: string;
  status: RunStatus;
  chunk_count: number | null;
  commit_sha: string | null;
  error: string | null;
  /** Files the run skipped (§7.1); [] if none. */
  skipped_files: SkippedFile[];
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface Resource {
  id: number;
  resource_type: ResourceType;
  source_kind: 'URL' | 'UPLOAD' | 'BOARD';
  display_name: string;
  url: string | null;
  repo_ref: string | null;
  upload_source_path: string | null;
  /** Uploads: every stored path; [] otherwise. */
  files: string[];
  last_commit_sha: string | null;
  created_at: string;
  /** One key per course profile; null until that profile has synced this resource. */
  latest_runs: Record<string, IngestionRun | null>;
}

export interface UploadResult extends Resource {
  skipped: SkippedFile[];
}

export interface ProfilePreset {
  name: string;
  embedding_model: string;
  /** §7.4: { default, pdf?, web?, markdown? }, each a chunker config. */
  chunking: Record<string, Record<string, unknown>>;
}

export interface IngestionProfile extends ProfilePreset {
  collection_name: string;
  created_at: string;
}

export interface RagSettings {
  enabled: boolean;
  active_profile: string;
  similarity_threshold: number;
  system_prompt: string;
  generation_model: string;
}
