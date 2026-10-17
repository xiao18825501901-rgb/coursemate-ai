"""Bounded, source-bound graph-degree questions for the existing point engine.

This is a trusted host author for four narrowly identified graph-degree targets.
It makes no model call and grants nothing outside the exact source, slot shape,
language and original Teaching Spec target supplied by the point host.
"""

import json
import sqlite3
from collections.abc import Callable
from typing import Any, Final, Literal

from pydantic import Field

from app.db import Database
from app.errors import ApiError
from app.learning.assessment_point_catalog import canonical_hash
from app.learning.assessment_point_question_inputs import AssessmentPointQuestionInput
from app.learning.deterministic_graph_grading import METHOD
from app.learning.model_operation_authority import authorize_model_operation
from app.learning.models import Contract, Identifier, Text
from app.learning.question_blueprint import Hex64
from app.learning.question_persistence import QuestionPersistenceResult
from app.learning.structured_calls import ModelCallClaim

DEGREE_RULE: Final = (
    "In an undirected graph, the degree of a vertex is the number of incident edges."
)
HANDSHAKE_RULE: Final = (
    "The sum of all vertex degrees equals twice the number of edges."
)

SUPPORTED_GRAPH_POINT_SHAPES: Final = {
    "vd_degree_definition_required": ("SHORT_TEXT", "definition"),
    "vd_handshake_identity_required": ("SHORT_TEXT", "definition"),
    "vd_even_odd_degree_count": ("EXPLANATION", "analysis"),
    "vd_doubling_misconception": ("EXPLANATION", "analysis"),
}


class DeterministicGraphStep(Contract):
    ordinal: int = Field(ge=1, le=12, strict=True)
    operation: Text
    result: Text
    explanation: Text
    source_refs: list[Identifier] = Field(min_length=1)


class DeterministicGraphPointContent(Contract):
    schema_version: Literal["deterministic-graph-point-content.v1"] = (
        "deterministic-graph-point-content.v1"
    )
    method: Literal["finite-loop-free-graph-degree-assessment.v1"] = METHOD
    point_input_hash: Hex64
    source_snapshot: Hex64
    content_language: Literal["zh-CN", "en"]
    question_text: Text
    reference_answer: Text
    solution_steps: list[DeterministicGraphStep] = Field(min_length=1, max_length=12)
    proof: dict[str, Any]


def _source_refs(point_input: AssessmentPointQuestionInput) -> list[str]:
    return list(
        dict.fromkeys(
            fragment.evidence_id
            for target in point_input.targets
            for fragment in target.evidence.fragments
        )
    )


def _source_text(point_input: AssessmentPointQuestionInput) -> str:
    return "\n".join(
        fragment.content
        for target in point_input.targets
        for fragment in target.evidence.fragments
    )


def _step(
    ordinal: int,
    operation: str,
    result: str,
    explanation: str,
    refs: list[str],
) -> DeterministicGraphStep:
    return DeterministicGraphStep(
        ordinal=ordinal,
        operation=operation,
        result=result,
        explanation=explanation,
        source_refs=refs,
    )


def _english(item_id: str, refs: list[str]) -> tuple[str, str, list[DeterministicGraphStep]]:
    graph = "V = {A, B, C, D} and E = {{A,B}, {A,C}, {B,C}, {C,D}}"
    degrees = "deg(A)=2, deg(B)=2, deg(C)=3, and deg(D)=1"
    if item_id == "vd_degree_definition_required":
        question = (
            "Consider the finite, undirected, loop-free simple graph with " + graph + ". "
            "Define the degree of a vertex, then compute the degree of every vertex."
        )
        answer = (
            "The degree of a vertex is the number of incident edges. " + degrees + "."
        )
        steps = [
            _step(1, "Apply the definition", DEGREE_RULE, "Use the supplied course rule.", refs),
            _step(2, "Count incident edges", degrees + ".", (
                "A meets AB and AC; B meets AB and BC; C meets AC, BC and CD; D meets CD."
            ), refs),
        ]
    elif item_id == "vd_handshake_identity_required":
        question = (
            "For the finite, undirected, loop-free simple graph with " + graph + ", "
            "state the degree-sum identity and verify it by independently counting "
            "all vertex degrees and the edges."
        )
        answer = (
            "The identity is sum_v deg(v)=2|E|. Here " + degrees
            + ", so the degree sum is 8. Independently, |E|=4, so 2|E|=8."
        )
        steps = [
            _step(1, "State the source rule", HANDSHAKE_RULE, (
                "Every undirected edge is incident to two endpoints."
            ), refs),
            _step(2, "Count degrees", degrees + "; their sum is 8.", (
                "The complete edge list gives the four incidence counts."
            ), refs),
            _step(3, "Count edges independently", "|E|=4 and 2|E|=8.", (
                "The two independently computed sides agree."
            ), refs),
        ]
    elif item_id == "vd_even_odd_degree_count":
        question = (
            "Using the degree-sum identity for finite, undirected, loop-free graphs, "
            "derive why the number of odd-degree vertices must be even. Then verify "
            "the conclusion on the graph with " + graph + "."
        )
        answer = (
            "The degree sum is 2|E| and is therefore even. Even-degree terms add no odd "
            "parity, so an even sum contains an even number of odd-degree terms. In the "
            "example, " + degrees + "; C and D are the two odd-degree vertices."
        )
        steps = [
            _step(1, "Use the handshake identity", "The total degree sum is even.", (
                "The supplied identity writes it as twice the integer |E|."
            ), refs),
            _step(2, "Apply integer parity", (
                "An even sum has an even number of odd summands."
            ), "Even-degree vertices do not change the parity of the sum.", refs),
            _step(3, "Verify the example", degrees + "; C and D are odd.", (
                "Exactly two vertices have odd degree, which is even."
            ), refs),
        ]
    else:
        question = (
            "A student claims that in a finite, undirected, loop-free graph the sum "
            "of all vertex degrees equals |E|. Evaluate the claim using the graph with "
            + graph + ", and explain the correct counting rule."
        )
        answer = (
            "The claim is false. " + degrees + ", so the degree sum is 8, while |E|=4. "
            "The correct identity is sum_v deg(v)=2|E|=8 because every edge contributes "
            "once at each of its two endpoints."
        )
        steps = [
            _step(1, "Compute both quantities", (
                degrees + "; the degree sum is 8 and |E|=4."
            ), "The complete graph description supports both independent counts.", refs),
            _step(2, "Correct the counting method", "The degree sum is 2|E|, not |E|.", (
                "Each undirected edge is counted at both endpoints, producing two incidences."
            ), refs),
        ]
    return question, answer, steps


def _chinese(item_id: str, refs: list[str]) -> tuple[str, str, list[DeterministicGraphStep]]:
    graph = "V={A, B, C, D}，E={{A,B}, {A,C}, {B,C}, {C,D}}"
    degrees = "deg(A)=2，deg(B)=2，deg(C)=3，deg(D)=1"
    if item_id == "vd_degree_definition_required":
        question = f"给定有限无向简单图（无自环）{graph}。请定义顶点的度，并计算每个顶点的度。"
        answer = f"顶点的度是与该顶点关联的边数。因此 {degrees}。"
        steps = [
            _step(1, "使用定义", "顶点的度等于关联边数。", "使用课程来源中的顶点度定义。", refs),
            _step(2, "逐点计数", degrees + "。", "分别从完整边集统计每个顶点出现的边。", refs),
        ]
    elif item_id == "vd_handshake_identity_required":
        question = (
            f"给定有限无向简单图（无自环）{graph}。"
            "写出度数和恒等式，并分别统计度数和边数加以验证。"
        )
        answer = f"恒等式为 Σdeg(v)=2|E|。本图 {degrees}，度数和为8；|E|=4，所以2|E|=8。"
        steps = [
            _step(1, "写出来源规则", "Σdeg(v)=2|E|。", "每条无向边连接两个端点。", refs),
            _step(2, "统计度数", degrees + "，总和为8。", "由完整边集逐点统计。", refs),
            _step(3, "独立统计边数", "|E|=4，2|E|=8。", "两种统计结果一致。", refs),
        ]
    elif item_id == "vd_even_odd_degree_count":
        question = (
            "利用有限无向图的度数和恒等式，推导奇度顶点个数为何必为偶数，"
            f"并用图 {graph} 验证。"
        )
        answer = (
            "度数和等于2|E|，所以是偶数；偶数个奇数相加才可能为偶数。"
            f"本图 {degrees}，奇度顶点为C、D，共2个。"
        )
        steps = [
            _step(1, "使用握手恒等式", "度数和为偶数。", "它等于整数|E|的两倍。", refs),
            _step(2, "应用奇偶性", "奇度项的个数必须为偶数。", "偶度项不改变总和的奇偶性。", refs),
            _step(3, "验证例图", degrees + "，C、D为奇度。", "奇度顶点共有2个。", refs),
        ]
    else:
        question = (
            "学生声称有限无向无自环图的度数和等于|E|。"
            f"请用图 {graph} 判断并解释正确的计数规则。"
        )
        answer = (
            f"该说法错误。本图 {degrees}，度数和为8，而|E|=4。"
            "正确关系是Σdeg(v)=2|E|，因为每条边在两个端点各计一次。"
        )
        steps = [
            _step(
                1,
                "分别计算",
                degrees + "；度数和为8，|E|=4。",
                "由完整图信息独立计算两者。",
                refs,
            ),
            _step(
                2,
                "纠正计数",
                "度数和等于2|E|而非|E|。",
                "每条无向边贡献两个端点关联次数。",
                refs,
            ),
        ]
    return question, answer, steps


def build_graph_point_content(
    point_input: AssessmentPointQuestionInput,
) -> DeterministicGraphPointContent | None:
    """Return a checkable host-authored item only for the exact bounded family."""

    if len(point_input.targets) != 1:
        return None
    target = point_input.targets[0]
    expected_shape = SUPPORTED_GRAPH_POINT_SHAPES.get(target.item_id)
    slot = point_input.point_slot
    source = _source_text(point_input)
    if (
        expected_shape is None
        or (slot.question_type, slot.task_form) != expected_shape
        or tuple(slot.original_target_item_ids) != (target.item_id,)
        or slot.verified_point.objective != target.objective
        or slot.verified_point.scoring_evidence != [target.acceptance]
        or DEGREE_RULE not in source
        or HANDSHAKE_RULE not in source
        or any(fragment.truncated for fragment in target.evidence.fragments)
    ):
        return None
    refs = _source_refs(point_input)
    question, answer, steps = (
        _chinese(target.item_id, refs)
        if point_input.content_language == "zh-CN"
        else _english(target.item_id, refs)
    )
    return DeterministicGraphPointContent(
        point_input_hash=point_input.identity(),
        source_snapshot=point_input.source_snapshot,
        content_language=point_input.content_language,
        question_text=question,
        reference_answer=answer,
        solution_steps=steps,
        proof={
            "schema_version": "deterministic-graph-point-proof.v1",
            "method": METHOD,
            "vertices": ["A", "B", "C", "D"],
            "edges": [["A", "B"], ["A", "C"], ["B", "C"], ["C", "D"]],
            "degrees": {"A": 2, "B": 2, "C": 3, "D": 1},
            "degree_sum": 8,
            "edge_count": 4,
            "twice_edge_count": 8,
            "odd_degree_vertices": ["C", "D"],
            "odd_degree_count": 2,
            "source_rules": [DEGREE_RULE, HANDSHAKE_RULE],
            "source_refs": refs,
            "model_http": 0,
        },
    )


def _encode(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _answer_payload(
    content: DeterministicGraphPointContent,
    question_type: str,
) -> dict[str, Any]:
    answer: dict[str, Any] = {
        "reference_answer": content.reference_answer,
        "solution_steps": [
            {"step_id": f"step_{step.ordinal}", **step.model_dump(mode="json")}
            for step in content.solution_steps
        ],
        "source_refs": content.proof["source_refs"],
        "deterministic_proof": content.proof,
        "verification_notice": "DETERMINISTIC_HOST_PROOF",
    }
    # The existing deterministic grader recognizes finite accepted answers for
    # SHORT_TEXT. Keep the private worked solution as the canonical answer and
    # expose only its exact normalized value to that existing grading contract.
    if question_type == "SHORT_TEXT":
        answer["accepted"] = [content.reference_answer]
    return answer


def _revision(
    point_input: AssessmentPointQuestionInput,
    content: DeterministicGraphPointContent,
) -> str:
    return canonical_hash(
        {
            "method": METHOD,
            "point_input": point_input.model_dump(mode="json"),
            "content": content.model_dump(mode="json"),
        }
    )


def _evidence_current(
    connection: sqlite3.Connection,
    point_input: AssessmentPointQuestionInput,
) -> bool:
    """Recheck immutable source bytes inside the publication transaction."""

    for target in point_input.targets:
        for fragment in target.evidence.fragments:
            row = connection.execute(
                "SELECT version.id AS version_id,version.document_id,version.version,"
                "version.sha256,chunk.content,chunk.locator_type,chunk.locator_value "
                "FROM chunks AS chunk JOIN chunk_source_versions AS source "
                "ON source.chunk_id=chunk.id JOIN document_versions AS version "
                "ON version.id=source.document_version_id WHERE chunk.id=?",
                (fragment.evidence_id,),
            ).fetchone()
            if row is None or (
                str(row["version_id"]) != fragment.document_version_id
                or str(row["document_id"]) != fragment.document_id
                or int(row["version"]) != fragment.document_version
                or str(row["sha256"]) != fragment.document_sha256
                or str(row["content"]) != fragment.content
                or f"{row['locator_type']}:{row['locator_value']}" != fragment.locator
            ):
                return False
            statuses = {
                str(item["status"])
                for item in connection.execute(
                    "SELECT status FROM material_evidence WHERE node_id=? AND chunk_id=? "
                    "AND document_version_id=?",
                    (
                        point_input.node_id,
                        fragment.evidence_id,
                        fragment.document_version_id,
                    ),
                ).fetchall()
            }
            if "REVOKED" in statuses and "ACTIVE" not in statuses:
                return False
    return True


class DeterministicGraphPointPublisher:
    """Append one host-proved item to the existing question pool, with zero HTTP."""

    def __init__(
        self,
        database: Database,
        verify_input: Callable[[ModelCallClaim, AssessmentPointQuestionInput], None],
    ) -> None:
        self.database = database
        self.verify_input = verify_input

    def prepare_or_read(
        self,
        claim: ModelCallClaim,
        point_input: AssessmentPointQuestionInput,
        *,
        operation_id: str | None = None,
    ) -> QuestionPersistenceResult | None:
        content = build_graph_point_content(point_input)
        if content is None:
            return None
        self.verify_input(claim, point_input)
        revision = _revision(point_input, content)
        question_id = "pointdet_" + revision
        family = "pointfamily_" + canonical_hash(
            {
                "configuration": point_input.configuration_id,
                "slot": point_input.point_slot.slot_key,
            }
        )
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if operation_id is not None:
                authorize_model_operation(
                    connection,
                    point_input.workspace_id,
                    operation_id,
                    expected_configuration_id=point_input.configuration_id,
                )
            if not _evidence_current(connection, point_input):
                raise ApiError(
                    409,
                    "ASSESSMENT_POINT_SOURCE_CHANGED",
                    "The original deterministic point source changed.",
                )
            saved = connection.execute(
                "SELECT question_revision_id,point_input_hash,content_json "
                "FROM assessment_point_deterministic_provenance "
                "WHERE configuration_id=? AND slot_id=?",
                (point_input.configuration_id, point_input.point_slot.slot_key),
            ).fetchone()
            if saved is not None:
                if (
                    str(saved["question_revision_id"]) != question_id
                    or str(saved["point_input_hash"]) != point_input.identity()
                    or json.loads(str(saved["content_json"]))
                    != content.model_dump(mode="json")
                ):
                    raise ApiError(
                        409,
                        "ASSESSMENT_POINT_PUBLICATION_CONFLICT",
                        "The deterministic point slot identity disagrees.",
                    )
                return self._result(question_id, True)
            self._insert_all(
                connection,
                point_input=point_input,
                content=content,
                question_id=question_id,
                revision=revision,
                family=family,
            )
        return self._result(question_id, False)

    def read_ready(
        self,
        claim: ModelCallClaim,
        point_input: AssessmentPointQuestionInput,
    ) -> QuestionPersistenceResult | None:
        content = build_graph_point_content(point_input)
        if content is None:
            return None
        self.verify_input(claim, point_input)
        revision = _revision(point_input, content)
        question_id = "pointdet_" + revision
        with self.database.connect() as connection:
            saved = connection.execute(
                "SELECT * FROM assessment_point_deterministic_provenance "
                "WHERE question_revision_id=? AND workspace_id=?",
                (question_id, point_input.workspace_id),
            ).fetchone()
            question = connection.execute(
                "SELECT prompt_text,options_json,answer_json,content_hash,"
                "validation_status,verification_method FROM assessment_question_revisions "
                "WHERE id=?",
                (question_id,),
            ).fetchone()
            reference = connection.execute(
                "SELECT steps_json,answer_json,source_refs_json,prompt_version "
                "FROM assessment_reference_solutions WHERE question_revision_id=?",
                (question_id,),
            ).fetchone()
            if (
                saved is None
                or question is None
                or reference is None
                or not _evidence_current(connection, point_input)
                or str(saved["point_input_hash"]) != point_input.identity()
                or json.loads(str(saved["point_input_json"]))
                != point_input.model_dump(mode="json")
                or json.loads(str(saved["content_json"]))
                != content.model_dump(mode="json")
                or json.loads(str(saved["proof_json"])) != content.proof
                or str(saved["method"]) != METHOD
                or str(saved["publication_status"]) != "READY"
                or str(question["prompt_text"]) != content.question_text
                or json.loads(str(question["options_json"])) != []
                or json.loads(str(question["answer_json"]))
                != _answer_payload(content, point_input.point_slot.question_type)
                or str(question["content_hash"]) != revision
                or str(question["validation_status"]) != "VALIDATED"
                or str(question["verification_method"]) != "DETERMINISTIC"
                or json.loads(str(reference["answer_json"])) != content.reference_answer
                or json.loads(str(reference["steps_json"]))
                != [
                    {"step_id": f"step_{step.ordinal}", **step.model_dump(mode="json")}
                    for step in content.solution_steps
                ]
                or json.loads(str(reference["source_refs_json"])) != _source_refs(point_input)
                or str(reference["prompt_version"]) != METHOD
            ):
                return None
        return self._result(question_id, True)

    @staticmethod
    def _result(question_id: str, idempotent: bool) -> QuestionPersistenceResult:
        return QuestionPersistenceResult(
            question_revision_id=question_id,
            status="READY",
            readiness_reason="EXACT_SOURCE_BOUND_DETERMINISTIC_GRAPH_PROOF",
            verification_method="DETERMINISTIC",
            idempotent=idempotent,
        )

    @staticmethod
    def _insert_all(
        connection: sqlite3.Connection,
        *,
        point_input: AssessmentPointQuestionInput,
        content: DeterministicGraphPointContent,
        question_id: str,
        revision: str,
        family: str,
    ) -> None:
        refs = _source_refs(point_input)
        steps = [
            {"step_id": f"step_{step.ordinal}", **step.model_dump(mode="json")}
            for step in content.solution_steps
        ]
        answer = _answer_payload(content, point_input.point_slot.question_type)
        connection.execute(
            "INSERT INTO assessment_question_revisions("
            "id,course_id,owner_user_id,family_id,revision,source_kind,question_type,"
            "difficulty,prompt_text,options_json,answer_json,validation_status,"
            "verification_method,content_hash,created_by_user_id) "
            "VALUES(?,?,?,?,1,'WORKSPACE_PRIVATE',?,?,?,'[]',?,'VALIDATED',"
            "'DETERMINISTIC',?,?)",
            (
                question_id,
                point_input.course_id,
                point_input.owner_user_id,
                family,
                point_input.point_slot.question_type,
                point_input.point_slot.target_difficulty,
                content.question_text,
                _encode(answer),
                revision,
                point_input.owner_user_id,
            ),
        )
        for ordinal, target in enumerate(point_input.targets, start=1):
            connection.execute(
                "INSERT INTO assessment_rubric_criteria("
                "question_revision_id,criterion_id,node_id,spec_version,item_id,"
                "dimension,max_fraction,description,deterministic_rule_json) "
                "VALUES(?,?,?,?,?,'METHOD_REASONING',100,?,?)",
                (
                    question_id,
                    f"point_target_{ordinal}",
                    point_input.node_id,
                    point_input.spec_version,
                    target.item_id,
                    target.acceptance,
                    _encode(content.proof),
                ),
            )
        connection.execute(
            "INSERT INTO assessment_reference_solutions("
            "id,question_revision_id,blueprint_item_id,solution_revision,steps_json,"
            "answer_json,source_refs_json,prompt_version,content_hash) "
            "VALUES(?,?,NULL,1,?,?,?,?,?)",
            (
                "pointdetsolution_" + revision[:40],
                question_id,
                _encode(steps),
                _encode(content.reference_answer),
                _encode(refs),
                METHOD,
                canonical_hash({"steps": steps, "answer": content.reference_answer, "refs": refs}),
            ),
        )
        source_scope = [
            entry.model_dump(mode="json")
            for target in point_input.targets
            for entry in target.evidence.source_scope()
        ]
        evidence_hash = canonical_hash(
            [target.evidence.identity() for target in point_input.targets]
        )
        run = {"method": METHOD, "authority": "TRUSTED_HOST", "model_http": 0}
        connection.execute(
            "INSERT INTO question_engine_provenance("
            "question_revision_id,workspace_id,blueprint_id,blueprint_hash,"
            "evidence_pack_hash,question_revision_hash,node_id,spec_version,objective_id,"
            "blueprint_json,evidence_ids_json,author_run_json,blind_input_hash,"
            "blind_output_json,blind_run_json,validation_report_json,publication_status,"
            "readiness_reason) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,"
            "'READY','EXACT_SOURCE_BOUND_DETERMINISTIC_GRAPH_PROOF')",
            (
                question_id,
                point_input.workspace_id,
                point_input.blueprint_id,
                point_input.identity(),
                evidence_hash,
                revision,
                point_input.node_id,
                point_input.spec_version,
                point_input.targets[0].item_id,
                _encode({
                    "schema_version": "deterministic-graph-point-blueprint.v1",
                    "source_scope": source_scope,
                    "point_input_hash": point_input.identity(),
                    "method": METHOD,
                }),
                _encode(refs),
                _encode(run),
                canonical_hash(content.proof),
                _encode(content.proof),
                _encode(run),
                _encode(content.proof),
            ),
        )
        connection.execute(
            "INSERT INTO assessment_point_deterministic_provenance("
            "question_revision_id,workspace_id,configuration_id,slot_id,node_id,"
            "spec_version,point_input_hash,question_revision_hash,point_input_json,"
            "content_json,proof_json,method,publication_status) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,'READY')",
            (
                question_id,
                point_input.workspace_id,
                point_input.configuration_id,
                point_input.point_slot.slot_key,
                point_input.node_id,
                point_input.spec_version,
                point_input.identity(),
                revision,
                point_input.model_dump_json(),
                content.model_dump_json(),
                _encode(content.proof),
                METHOD,
            ),
        )
        connection.execute(
            "INSERT INTO assessment_configuration_questions("
            "configuration_id,workspace_id,slot_id,ordinal,question_revision_id,"
            "family_id,blueprint_id,objective_id,primary_point_id,"
            "point_validation_receipt_id) VALUES(?,?,?,?,?,?,?,?,?,NULL)",
            (
                point_input.configuration_id,
                point_input.workspace_id,
                point_input.point_slot.slot_key,
                point_input.point_slot.ordinal,
                question_id,
                family,
                point_input.blueprint_id,
                point_input.point_slot.primary_point_id,
                point_input.point_slot.primary_point_id,
            ),
        )
