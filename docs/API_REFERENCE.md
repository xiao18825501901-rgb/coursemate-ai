# API Reference

Local base URLs are http://localhost:8000 for RAG and http://localhost:8001 for Agent. JSON uses camelCase. Unknown request properties are rejected where a body schema is defined.

## Shared error envelope

    {
      "error": {
        "code": "VALIDATION_ERROR",
        "message": "Human-readable summary.",
        "details": {}
      }
    }

Expected codes include VALIDATION_ERROR, COURSE_NOT_FOUND, DOCUMENT_NOT_FOUND, JOB_NOT_FOUND, DUPLICATE_DOCUMENT, UNSUPPORTED_FILE_TYPE, FILE_TOO_LARGE, TASK_NOT_FOUND, RATE_LIMITED, OPENAI_NOT_CONFIGURED, MODEL_ERROR, and ROUTE_NOT_FOUND.

## RAG API

### GET /health

Returns 200 with { status: "ok", service: "rag-api" }.

### POST /api/courses

Creates a course and returns 201.

    { "id": "cs3481", "name": "CS3481", "description": "Computer graphics" }

id must match lowercase letters/digits/hyphens, 2-50 characters. Duplicate IDs return 409.

### GET /api/courses?page=1&pageSize=50

Returns { items, page, pageSize, total }. pageSize is capped at 100.

### GET /api/courses/:courseId/documents?page=1&pageSize=50

Lists document metadata and status for one course. Returns 404 when the course does not exist.

### POST /api/courses/:courseId/documents

multipart/form-data with field file. Returns 202 with { document, job }. Poll the returned job ID. Supported extensions: .pdf, .md, .markdown, .txt, .docx, and .pptx. The default maximum is 20 MiB.

### GET /api/ingestion-jobs/:jobId

Returns status queued, processing, completed, or failed plus processedChunks and errorMessage.

### POST /api/qa/chat

Request:

    { "courseId": "cs3481", "question": "How does DBSCAN identify a core point?" }

Returns text/event-stream. A successful evidence-backed stream has this order:

    event: meta
    data: {"requestId":"qa_...","conversationId":"conv_...","courseId":"cs3481","retrievedChunks":6}

    event: delta
    data: {"text":"..."}

    event: citation
    data: {"sourceLabel":"S1","courseId":"cs3481","filename":"...","locatorType":"page","locatorValue":"12","excerpt":"...","channels":["keyword","vector"]}

    event: done
    data: {"requestId":"qa_..."}

When no chunk is available, delta contains the evidence-insufficient message and no citation event is emitted. A model failure emits event: error with a safe message.

## Agent API

### GET /health

Returns 200 with { status: "ok", service: "agent-api" }.

### GET /api/tasks

Query parameters: page (default 1), pageSize (default 50, max 100), courseId, status, and q. Returns { items, page, pageSize, total }.

### POST /api/tasks

Creates a task and returns 201. Required title; optional notes, courseId, priority, dueDate, and sourceCitation.

    {
      "title": "Review DBSCAN",
      "courseId": "cs3481",
      "priority": "high",
      "dueDate": "2026-08-20",
      "sourceCitation": {
        "filename": "lecture.pdf",
        "locator": "page 12",
        "excerpt": "A core point..."
      }
    }

### PATCH /api/tasks/:taskId

Updates one or more mutable fields and returns the task. To clear nullable values, send null. An empty body is rejected.

### DELETE /api/tasks/:taskId

Returns 204. A missing task returns 404 TASK_NOT_FOUND.

### POST /api/agent/chat

Request: { "message": "Add a high priority GE2324 revision task due 2026-08-20" }.

Returns 200 with a final message and tool execution trace:

    {
      "message": "The requested task action completed.",
      "toolResults": [
        { "callId": "...", "name": "create_task", "result": { "ok": true, "data": { } } }
      ]
    }

The API may return 502 for an unavailable/model failure. Direct task CRUD remains available independently.
## Operational controls

The Agent accepts JSON bodies up to 64 KiB and applies 120 requests per minute per client. Both APIs allow only the configured WEB_ORIGIN through CORS. Agent responses use Helmet headers; RAG adds nosniff, DENY framing, and no-referrer headers.
