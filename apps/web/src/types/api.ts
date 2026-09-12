export interface ApiErrorBody {
  error: {
    code: string;
    message: string;
    details: Record<string, unknown>;
  };
}

export interface Page<T> {
  items: T[];
  page: number;
  pageSize: number;
  total: number;
}

export interface Course {
  id: string;
  name: string;
  description: string;
  courseType: "official" | "user";
  visibility: "private" | "public";
  publicationStatus: "private" | "pending" | "published" | "rejected";
  preferredLanguage: LanguagePreference;
  documentCount?: number;
  indexStatus?: "empty" | "indexing" | "indexed" | "failed";
  publishedAt: string | null;
  isOwner: boolean;
  canManage: boolean;
  createdAt: string;
  updatedAt: string;
}

export interface CourseCreateInput {
  id: string;
  name: string;
  description: string;
}

export interface CourseUpdateInput {
  name?: string;
  description?: string;
  preferredLanguage?: LanguagePreference;
}

export type DocumentStatus = "pending" | "processing" | "ready" | "failed" | "unsupported";

export interface CourseDocument {
  id: string;
  courseId: string;
  filename: string;
  mediaType: string;
  extension: string;
  sha256: string;
  byteSize: number;
  status: DocumentStatus;
  chunkCount: number;
  errorMessage: string | null;
  createdAt: string;
  updatedAt: string;
}

export interface IngestionJob {
  id: string;
  documentId: string;
  status: "queued" | "processing" | "completed" | "failed";
  processedChunks: number;
  errorMessage: string | null;
  createdAt: string;
  updatedAt: string;
}

export interface UploadAccepted {
  document: CourseDocument;
  job: IngestionJob;
}

export interface TeachingProfileInput {
  language: LanguagePreference;
  studentLevel: "beginner" | "intermediate" | "advanced";
  learningGoal: string;
  teachingStyles: Array<"intuition-first" | "step-by-step" | "socratic" | "analogy" | "worked-examples">;
  answerDepth: "concise" | "balanced" | "detailed";
  examplePreference: "minimal" | "when-helpful" | "worked";
  exercisePolicy: "none" | "offer" | "always";
  examOrientation: boolean;
  citationPreference: "standard" | "detailed";
  mathDetailLevel: "light" | "standard" | "full";
  terminologyStyle: "plain" | "bilingual" | "formal";
  customRequirements: string;
}

export interface TeachingProfilePreview extends TeachingProfileInput {
  generatedPrompt: string;
}

export interface TeachingProfile extends TeachingProfilePreview {
  id: string;
  courseId: string;
  version: number;
  createdAt: string;
  updatedAt: string;
}

export interface PublicationRequest {
  id: string;
  courseId: string;
  courseName: string;
  status: "pending" | "approved" | "rejected" | "withdrawn";
  shareMaterialsConsent: boolean;
  rightsConfirmation: boolean;
  consentVersion: string;
  consentedAt: string;
  submittedAt: string;
  reviewedAt: string | null;
  reviewNote: string;
  snapshotId: string | null;
  snapshotHash: string | null;
  resourceCount: number;
}

export type PublicationSubjectKind = "COURSE" | "OFFICIAL_KNOWLEDGE" | "OVERLAY";

export interface PublicationSnapshotResource {
  kind: string;
  id: string;
  version: string;
  displayName: string;
  sourceScope: string;
  contentHash: string;
  metadata: Record<string, unknown>;
}

export interface PublicationSnapshot {
  id: string;
  subjectKind: PublicationSubjectKind;
  requestId: string;
  courseId: string;
  workspaceId: string | null;
  contentHash: string;
  createdAt: string;
  summary: Record<string, unknown>;
  resources: PublicationSnapshotResource[];
}

export interface OfficialKnowledgeDraft {
  treeVersionId: string;
  courseId: string;
  courseName: string;
  treeVersion: number;
  title: string;
  memberCount: number;
  pendingRequestId: string | null;
}

export interface OfficialKnowledgePublicationRequest {
  id: string;
  courseId: string;
  courseName: string;
  treeVersionId: string;
  treeVersion: number;
  treeTitle: string;
  status: "pending" | "approved" | "rejected" | "withdrawn";
  submittedAt: string;
  reviewedAt: string | null;
  reviewNote: string;
  snapshotId: string;
  snapshotHash: string;
  resourceCount: number;
}

export interface OverlayPublicationSubmitInput {
  nodeIds: string[];
  documentVersionIds: string[];
  artifactIds: string[];
  evidenceIds: string[];
  shareSelectedContentConsent: boolean;
  rightsConfirmation: boolean;
  consentVersion: string;
}

export interface OverlayPublicationRequest {
  id: string;
  courseId: string;
  courseName: string;
  workspaceId: string;
  status: "pending" | "approved" | "rejected" | "withdrawn";
  shareSelectedContentConsent: boolean;
  rightsConfirmation: boolean;
  consentVersion: string;
  consentedAt: string;
  submittedAt: string;
  reviewedAt: string | null;
  reviewNote: string;
  snapshotId: string;
  snapshotHash: string;
  resourceCount: number;
}

export interface OverlayPublicationCandidates {
  nodes: Array<{ id: string; title: string; kind: string; specVersion: number | null }>;
  documents: Array<{
    id: string;
    documentId: string;
    version: number;
    filename: string;
    sha256: string;
    byteSize: number;
    status: string;
  }>;
  artifacts: Array<{
    id: string;
    documentVersionId: string;
    kind: string;
    producerVersion: string;
    sha256: string;
    byteSize: number;
  }>;
  evidence: Array<{
    id: string;
    nodeId: string;
    nodeTitle: string;
    nodeIsPrivate: boolean;
    documentVersionId: string;
    locatorType: string;
    locatorValue: string;
  }>;
}

export interface Citation {
  sourceLabel: string;
  courseId: string;
  documentId: string;
  chunkId: string;
  filename: string;
  locatorType: string;
  locatorValue: string;
  section: string | null;
  excerpt: string;
  channels: string[];
}

export type LanguagePreference = "auto" | "zh-CN" | "en" | "bilingual";

export interface ConversationSummary {
  id: string;
  courseId: string;
  title: string;
  preferredLanguage: LanguagePreference;
  messageCount: number;
  createdAt: string;
  updatedAt: string;
}

export interface ConversationMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  citations: Citation[];
  metadata?: QaStreamMeta;
  createdAt: string;
}

export interface ConversationDetail extends Omit<ConversationSummary, "messageCount"> {
  messages: ConversationMessage[];
}

export type QueryIntent =
  | "COURSE_GROUNDED"
  | "COURSE_TUTORING"
  | "GENERAL_CONVERSATION"
  | "COURSE_META"
  | "AMBIGUOUS";

export type GroundingMode = "grounded" | "mixed" | "general" | "metadata";

export interface QaStreamMeta {
  requestId?: string;
  conversationId?: string;
  courseId?: string;
  retrievedChunks?: number;
  queryIntent?: QueryIntent;
  groundingMode?: GroundingMode;
  retrievalQueryRewritten?: boolean;
  teachingApproach?: "formal" | "analogy" | "worked_example" | "socratic" | null;
}

export type TaskStatus = "todo" | "in_progress" | "completed";
export type TaskPriority = "low" | "medium" | "high";

export interface SourceCitation {
  filename: string;
  locator: string;
  excerpt: string;
}

export interface Task {
  id: string;
  title: string;
  notes: string | null;
  courseId: string | null;
  status: TaskStatus;
  priority: TaskPriority;
  dueDate: string | null;
  sourceCitation: SourceCitation | null;
  createdAt: string;
  updatedAt: string;
  completedAt: string | null;
}

export interface CreateTaskInput {
  title: string;
  notes?: string | null;
  courseId?: string | null;
  priority?: TaskPriority;
  dueDate?: string | null;
  sourceCitation?: SourceCitation | null;
}

export interface UpdateTaskInput {
  title?: string;
  notes?: string | null;
  courseId?: string | null;
  status?: TaskStatus;
  priority?: TaskPriority;
  dueDate?: string | null;
}

export interface ToolResult {
  ok: boolean;
  data: unknown;
  error: { code: string; message: string } | null;
}

export interface AgentChatResponse {
  message: string;
  toolResults: ToolResult[];
}
