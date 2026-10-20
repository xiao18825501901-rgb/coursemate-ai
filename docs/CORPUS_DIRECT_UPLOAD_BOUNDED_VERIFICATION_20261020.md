# Bounded verification for direct PDF uploads

The existing direct-upload API contract is unchanged. PDF objects in OSS are now verified in ordered 1 MiB byte ranges instead of loading the complete object into process memory during finalization.

The verifier requires every requested range to return its exact expected length, validates the PDF header from the first range, computes SHA-256 over every byte in order, and preserves the existing size limit and hash-mismatch errors. A verified range is never written as the complete local PDF cache: the existing ingestion worker hydrates the canonical OSS object under its capacity reservation before parsing. Non-PDF formats keep their prior whole-content validation because Office and image validators inspect complete containers.

This change does not increase ordinary student upload limits, alter authentication, expose OSS credentials, modify schema, or create a second ingestion pipeline. Large administrator corpus imports still require the existing trusted manifest and capacity controls.

Verification evidence:

- The regression test failed before the change because a 2 MiB PDF generated one full-object range read.
- After the change, the same test requires at least three reads and caps every read at 1 MiB.
- A follow-up regression test first reproduced the truncated-cache defect and now proves that bounded verification leaves hydration to the ingestion worker.
- The complete direct-storage test module passes, including hash promotion, permissions, capacity recovery, duplicate races, range downloads and administrator-path safeguards.
