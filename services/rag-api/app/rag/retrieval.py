from dataclasses import replace

from app.rag.embeddings import EmbeddingProvider
from app.rag.types import SearchHit
from app.repositories.chunks import ChunkRepository


def reciprocal_rank_fusion(
    keyword_hits: list[SearchHit],
    vector_hits: list[SearchHit],
    *,
    top_k: int,
    rank_constant: int = 60,
) -> list[SearchHit]:
    """Fuse incomparable channel scores by their ranks."""

    if top_k <= 0:
        return []
    scores: dict[str, float] = {}
    hits_by_id: dict[str, SearchHit] = {}
    channels: dict[str, list[str]] = {}
    for channel_hits in (keyword_hits, vector_hits):
        for rank, item in enumerate(channel_hits, start=1):
            scores[item.chunk_id] = scores.get(item.chunk_id, 0.0) + 1.0 / (
                rank_constant + rank
            )
            hits_by_id.setdefault(item.chunk_id, item)
            names = channels.setdefault(item.chunk_id, [])
            for channel in item.channels:
                if channel not in names:
                    names.append(channel)

    ranked_ids = sorted(scores, key=lambda item_id: (-scores[item_id], item_id))[:top_k]
    return [
        replace(
            hits_by_id[item_id],
            score=scores[item_id],
            channels=tuple(channels[item_id]),
        )
        for item_id in ranked_ids
    ]


class HybridRetriever:
    def __init__(
        self,
        repository: ChunkRepository,
        embedding_provider: EmbeddingProvider,
    ) -> None:
        self.repository = repository
        self.embedding_provider = embedding_provider

    def retrieve(self, *, course_id: str, query: str, top_k: int) -> list[SearchHit]:
        cleaned_query = query.strip()
        if not cleaned_query or top_k <= 0:
            return []
        candidate_limit = max(top_k * 3, top_k)
        keyword_hits = self.repository.keyword_search(
            course_id,
            cleaned_query,
            limit=candidate_limit,
        )
        query_vector = self.embedding_provider.embed_texts([cleaned_query])[0]
        vector_hits = self.repository.vector_search(
            course_id,
            query_vector,
            limit=candidate_limit,
        )
        return reciprocal_rank_fusion(keyword_hits, vector_hits, top_k=top_k)
