from app.tutor.routing import QueryIntent, route_query


def test_routes_general_conversation_without_forcing_course_search() -> None:
    for query in ("你好", "跟我聊两句", "I feel tired today, how should I study?"):
        assert route_query(query).intent is QueryIntent.GENERAL_CONVERSATION


def test_routes_explicit_course_evidence_requests_as_grounded() -> None:
    for query in (
        "课件中 DBSCAN 是怎么定义的？",
        "According to lecture 7, what are the Phong terms?",
        "老师的 slides 对 core point 怎么说？",
    ):
        assert route_query(query).intent is QueryIntent.COURSE_GROUNDED


def test_routes_teaching_and_confusion_requests_as_tutoring() -> None:
    queries = ("为什么要定义 core point？", "给我举一道题", "我还是不懂", "Teach me step by step")
    for query in queries:
        assert route_query(query).intent is QueryIntent.COURSE_TUTORING


def test_routes_course_metadata_and_ambiguous_queries() -> None:
    assert route_query("这门课有哪些资料？").intent is QueryIntent.COURSE_META
    assert route_query("DBSCAN").intent is QueryIntent.AMBIGUOUS


def test_explicit_grounding_wins_over_generic_teaching_word() -> None:
    result = route_query("请解释课件中 DBSCAN 的正式定义")
    assert result.intent is QueryIntent.COURSE_GROUNDED
    assert result.uses_course_retrieval is True
