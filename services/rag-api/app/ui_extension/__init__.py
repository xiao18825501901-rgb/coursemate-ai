"""CourseMate UI-refresh extension: real V3 wiring for the `cm_update` application.

`app.cm_update` is the delivered new-UI backend. This package supplies the two
adapter points that the delivery package intentionally left open:

* :mod:`app.ui_extension.domain` -- a real ``DomainPort`` over the existing V3
  RAG database, ingestion service, HybridRetriever and Node task agent.
* :mod:`app.ui_extension.identity` -- a ``subject_resolver`` that returns the
  Clerk subject already verified by :mod:`app.auth`.

Nothing here replaces V3 storage, retrieval, assessment, knowledge-tree or
publication behaviour; every operation is delegated to the existing service.
"""

from app.ui_extension.domain import V3DomainAdapter
from app.ui_extension.identity import clerk_subject_resolver
from app.ui_extension.mount import mount_ui_extension

__all__ = ["V3DomainAdapter", "clerk_subject_resolver", "mount_ui_extension"]