"""Deterministic builder/validator for the auditable Jev judgment dataset.

Builds ``benchmarks/jev-judgments.dataset.json`` and the frozen split manifest
``benchmarks/jev-calibration.split.json`` with NO network and NO model calls.

Honesty rules baked in:

* Anything a rule, an ID, a sum or arithmetic can verify is **generated and checked by
  code** and labelled ``OBJECTIVE_VERIFIED`` (exact-locator hits, a candidate provably
  the only one citing the required condition, negation flips, numeric/arithmetic).
* Semantic cases cite a real course source (the in-repo ``data/inventory`` and
  ``data/transcriptions`` corpus) and record the review reason -> ``SOURCE_REVIEWED``.
* Where no source can be cited, the label is ``SILVER_DEEPSEEK`` and is marked
  unreviewed (not human gold).
* A small number of genuinely disputed cases stay ``DISPUTED`` with both readings.
* Split leakage control: splits are assigned by (document_id, node_id, question_family)
  group, never by row. The same underlying question with different numbers shares one
  group and therefore one split; this is asserted in code and in a test.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAG_SERVICE = ROOT / "services" / "rag-api"
sys.path.insert(0, str(RAG_SERVICE))

from app.evaluation.jev_semantic_ablation import (
    DATASET_STATUS_LABELLED,
    DATASET_VERSION,
    DEFINITION_VERSION,
    GROUPING_KEYS,
    LABEL_TIER_DISPUTED,
    LABEL_TIER_OBJECTIVE,
    LABEL_TIER_SILVER,
    LABEL_TIER_SOURCE,
    JevJudgment,
    build_split_manifest,
    load_jev_dataset,
    validate_jev_dataset,
    validate_split_leakage,
)

DATASET_PATH = ROOT / "benchmarks" / "jev-judgments.dataset.json"
SPLIT_PATH = ROOT / "benchmarks" / "jev-calibration.split.json"
CATALOG_PATH = RAG_SERVICE / "app" / "jev" / "decision_catalog.json"

# ----------------------------------------------------------------------------- catalog


def _catalog() -> dict:
    return json.loads(CATALOG_PATH.read_text(encoding="utf-8"))


def _questions_by_key() -> dict:
    return {q["key"]: q for q in _catalog()["questions"]}


# ----------------------------------------------------------------------------- helpers

NOUL_CRITERIA = {
    "false": "no, the statement does not hold",
    "true": "yes, the statement holds",
}

NOUL_INSTRUCTIONS = (
    "Does the supplied source substantively support the exact claim under the stated "
    "conditions? Judge the source, not outside world truth."
)

KEEP_SEGMENT_INSTRUCTIONS = (
    "Is this optional old segment needed to resolve the current request, preserve a "
    "still-relevant constraint, or understand an unresolved error?"
)


def _judgment(
    sample_id, definition_id, language, document_id, node_id, question_family,
    label_tier, label_evidence, state, question, label,
):
    criteria = question.get("criteria")
    if question["type"] == "score":
        option_count = len(criteria) if isinstance(criteria, dict) else len(criteria or [])
    elif question["type"] == "choice":
        option_count = len(criteria) if isinstance(criteria, dict) else 2
    else:
        option_count = 2
    return JevJudgment(
        sample_id=sample_id,
        definition_id=definition_id,
        definition_version=DEFINITION_VERSION,
        language=language,
        option_count=option_count,
        document_id=document_id,
        node_id=node_id,
        question_family=question_family,
        label_tier=label_tier,
        label_evidence=label_evidence,
        state=state,
        questions={"q": question},
        label={"q": label},
        split="",
    )


def _choice(definition_id, criteria, instructions=None):
    q = _questions_by_key()[definition_id]
    return {"type": "choice", "instructions": instructions or q["instructions"], "criteria": criteria}


def _score(definition_id, criteria):
    q = _questions_by_key()[definition_id]
    return {"type": "score", "instructions": q["instructions"], "criteria": criteria}


def _noul(instructions):
    return {"type": "noul", "instructions": instructions, "criteria": NOUL_CRITERIA}


def _sid(samples):
    return f"jev-{len(samples) + 1:04d}"


# ----------------------------------------------------------------------------- deterministic rules

_WORD_CHARS = "a-z0-9"


def _contains(text, term):
    """Case-insensitive term match: word-boundary for ASCII word-ish terms, substring otherwise.

    Word boundaries prevent substring collisions such as "mean" matching inside
    "k-means" or "assign" matching inside "assigned"/"assigns". Punctuation-bearing and
    non-ASCII terms (e.g. "-1", "+1", "f = ma", "a² + b² = c²") fall back to plain
    substring, which is exact for those literal tokens.
    """
    text = text.lower()
    term = term.lower()
    compact = term.replace("-", "").replace(" ", "")
    if term.isascii() and compact.isalnum():
        pattern = rf"(?<![{_WORD_CHARS}]){re.escape(term)}(?![{_WORD_CHARS}])"
        return re.search(pattern, text) is not None
    return term in text


def _retrieval_rule_score(text, topic_terms, component_terms, condition_terms):
    """Deterministic relevance score 0-4 from a candidate text (the code-verified rule).

    0 = unrelated (no topic, no component); 1 = topic/background only; 2 = component(s)
    without condition; 3 = some components + a condition; 4 = all components + a condition.
    """
    has_topic = any(_contains(text, t) for t in topic_terms)
    n_comp = sum(1 for t in component_terms if _contains(text, t))
    n_cond = sum(1 for t in condition_terms if _contains(text, t))
    if n_comp == 0 and not has_topic:
        return 0
    if n_comp == 0:
        return 1
    if n_cond == 0:
        return 2
    if n_comp == len(component_terms):
        return 4
    return 3


def _noul_support(source_span, must_contain, must_not_contain):
    if any(_contains(source_span, t) for t in must_not_contain):
        return False
    return all(_contains(source_span, t) for t in must_contain)


def _span_select(candidate_spans, must_contain):
    hits = [
        span_id
        for span_id, text in candidate_spans.items()
        if all(_contains(text, t) for t in must_contain)
    ]
    if len(hits) == 1:
        return hits[0]
    return "NO_SUPPORT"


def _corpus_quality_score(parse_flags, has_structure, has_source):
    if "missing_essential_structure" in parse_flags or not has_structure:
        return 0
    if "substantial_omissions" in parse_flags:
        return 1
    if "minor_parse_limitation" in parse_flags or not has_source:
        return 2
    return 3


# ----------------------------------------------------------------------------- content builders


def _build_retrieval(samples):
    atoms = [
        {
            "doc": "doc-cs3481-clustering", "node": "node-dbscan-core", "language": "en",
            "query": "What defines a DBSCAN core point?",
            "topic": ["dbscan", "core point", "density", "clustering"],
            "components": ["minpts", "eps"], "conditions": ["neighbours", "radius"],
            "candidates": [
                "A core point in DBSCAN has at least minPts neighbours within radius eps.",
                "A core point needs at least minPts neighbours to be dense.",
                "DBSCAN core points are defined using the minPts parameter.",
                "DBSCAN is a density-based clustering algorithm.",
                "Naive Bayes estimates the probability of each class from word counts.",
            ],
        },
        {
            "doc": "doc-cs3481-clustering", "node": "node-kmeans-centroid", "language": "en",
            "query": "How is a K-means centroid updated?",
            "topic": ["k-means", "kmeans", "centroid", "cluster", "clustering"],
            "components": ["centroid", "assigned"], "conditions": ["mean", "recomputed"],
            "candidates": [
                "Each K-means centroid is recomputed as the mean of the points assigned to its cluster.",
                "The K-means centroid is recomputed as the mean of its cluster.",
                "K-means assigns every point to its nearest centroid.",
                "K-means is a popular clustering method.",
                "Linear regression fits a straight line through the data points.",
            ],
        },
        {
            "doc": "doc-cs3481-trees", "node": "node-bst-rotation", "language": "en",
            "query": "What does a left rotation of a binary search tree do?",
            "topic": ["rotation", "binary search tree", "bst", "tree"],
            "components": ["right child", "rotate"], "conditions": ["in-order", "preserve"],
            "candidates": [
                "A left rotation will rotate the right child up and preserve the in-order traversal order.",
                "A left rotation will rotate the tree and preserve the in-order order.",
                "A left rotation moves the right child up.",
                "A binary search tree stores keys in a sorted structure.",
                "Heap sort repeatedly extracts the maximum from a binary heap.",
            ],
        },
        {
            "doc": "doc-ge2324-centrality", "node": "node-degree-centrality", "language": "en",
            "query": "What is degree centrality in a network?",
            "topic": ["degree centrality", "centrality", "network", "node"],
            "components": ["degree", "edges"], "conditions": ["number", "neighbours"],
            "candidates": [
                "Degree centrality counts the number of edges incident to a node, i.e. its direct neighbours.",
                "Degree centrality is measured by the number of direct neighbours of a node.",
                "Degree centrality uses the degree of each node.",
                "Centrality measures how central a node is in a network.",
                "Pearson correlation measures the linear association between two variables.",
            ],
        },
        {
            "doc": "doc-cs3481-correlation", "node": "node-pearson-range", "language": "en",
            "query": "What is the range of the Pearson correlation coefficient?",
            "topic": ["pearson", "correlation", "coefficient", "linear"],
            "components": ["correlation", "coefficient"], "conditions": ["-1", "+1"],
            "candidates": [
                "The Pearson correlation coefficient lies between -1 and +1.",
                "Pearson correlation ranges from -1 to +1.",
                "The Pearson coefficient measures linear correlation.",
                "Pearson is a measure of association between two variables.",
                "Gini impurity measures how often a randomly chosen element would be misclassified.",
            ],
        },
        {
            "doc": "doc-zh-pythagoras", "node": "node-gougu", "language": "zh",
            "query": "勾股定理说明了什么？",
            "topic": ["勾股", "直角三角形", "直角"],
            "components": ["斜边", "直角边"], "conditions": ["等于", "平方"],
            "candidates": [
                "勾股定理：直角三角形两条直角边的平方和等于斜边的平方。",
                "斜边的平方等于另外两条边的平方和。",
                "勾股定理涉及斜边和直角边。",
                "勾股定理是直角三角形的一个重要性质。",
                "牛顿第二定律指出力等于质量乘以加速度。",
            ],
        },
        {
            "doc": "doc-zh-quadratic", "node": "node-yiyuan", "language": "zh",
            "query": "一元二次方程的判别式如何决定根的数量？",
            "topic": ["一元二次方程", "判别式", "根"],
            "components": ["判别式", "根"], "conditions": ["大于零", "两个"],
            "candidates": [
                "当判别式大于零时，一元二次方程有两个不相等的实根。",
                "当大于零时，方程有两个实根。",
                "一元二次方程使用判别式来判断根。",
                "一元二次方程是含有一个未知数的二次方程。",
                "矩阵乘法要求左矩阵的列数等于右矩阵的行数。",
            ],
        },
        {
            "doc": "doc-zh-newton", "node": "node-niudun", "language": "zh",
            "query": "牛顿第二定律的内容是什么？",
            "topic": ["牛顿第二定律", "力", "加速度"],
            "components": ["力", "加速度"], "conditions": ["等于", "质量"],
            "candidates": [
                "牛顿第二定律：力等于质量乘以加速度。",
                "牛顿第二定律说明力与质量有关。",
                "牛顿第二定律涉及力和加速度。",
                "牛顿第二定律是一个重要的物理定律。",
                "条件概率表示在事件 B 发生的条件下事件 A 发生的概率。",
            ],
        },
        {
            "doc": "doc-zh-probability", "node": "node-tiaojian", "language": "zh",
            "query": "条件概率如何定义？",
            "topic": ["条件概率", "概率", "事件"],
            "components": ["事件", "联合概率"], "conditions": ["之比"],
            "candidates": [
                "条件概率定义为在事件 B 发生的条件下事件 A 发生的概率，等于联合概率与 B 的概率之比。",
                "条件概率等于联合概率与边缘概率之比。",
                "条件概率研究事件之间的发生关系。",
                "条件概率是概率论中的一个基本概念。",
                "聚类分析把相似的数据点划分到同一组。",
            ],
        },
        {
            "doc": "doc-zh-matrix", "node": "node-juzhen", "language": "zh",
            "query": "矩阵乘法的维度要求是什么？",
            "topic": ["矩阵", "乘法"],
            "components": ["列数", "行数"], "conditions": ["等于", "相乘"],
            "candidates": [
                "矩阵乘法要求左矩阵的列数等于右矩阵的行数才能相乘。",
                "矩阵乘法要求左矩阵的列数等于右矩阵的对应维度。",
                "矩阵乘法涉及列数和行数。",
                "矩阵乘法是线性代数中的基本运算。",
                "微分是研究函数变化率的工具。",
            ],
        },
    ]
    return _append_retrieval_atoms(samples, atoms)


def _append_retrieval_atoms(samples, atoms):
    """Append one atom's five candidates, scoring each with the code-verified rule.

    Factored out so content added *after* every other family (see
    ``_build_split_coverage_atoms``) produces samples through exactly the same rule and the
    same shape as the original ones. Sample ids continue from the current length, which is
    why new content is appended last rather than inserted: a positional id scheme would
    renumber every later sample, and the reports quote ids.
    """
    for atom in atoms:
        scores = [
            _retrieval_rule_score(text, atom["topic"], atom["components"], atom["conditions"])
            for text in atom["candidates"]
        ]
        if sorted(scores) != [0, 1, 2, 3, 4]:
            raise AssertionError(f"retrieval atom {atom['node']} scores {scores} do not cover 0..4.")
        for idx, text in enumerate(atom["candidates"]):
            score = scores[idx]
            samples.append(
                _judgment(
                    sample_id=_sid(samples),
                    definition_id="retrieval.support.v1",
                    language=atom["language"],
                    document_id=atom["doc"],
                    node_id=atom["node"],
                    question_family="retrieval",
                    label_tier=LABEL_TIER_OBJECTIVE,
                    label_evidence=(
                        "code-verified: retrieval rule_score -> "
                        f"{score} (topic={any(_contains(text, t) for t in atom['topic'])}, "
                        f"components={[t for t in atom['components'] if _contains(text, t)]}, "
                        f"conditions={[t for t in atom['conditions'] if _contains(text, t)]})"
                    ),
                    state={
                        "query": atom["query"], "exact_target": None, "top_k": 3,
                        "candidate_id": f"{atom['node']}-c{idx}", "candidate_text": text,
                        "source_metadata": {"course": atom["doc"], "locator": atom["doc"]},
                    },
                    question=_score("retrieval.support.v1", _questions_by_key()["retrieval.support.v1"]["criteria"]),
                    label={"score_index": score},
                )
            )
    return samples


def _build_claim(samples):
    pairs = [
        # (lang, doc, node, claim, source_span, must_contain, must_not_contain, tier)
        ("en", "doc-cs3481-clustering", "node-dbscan-params",
         "DBSCAN requires the parameters eps and minPts.",
         "DBSCAN takes two parameters: eps and minPts.", ["eps", "minpts"], [], LABEL_TIER_OBJECTIVE),
        ("en", "doc-cs3481-clustering", "node-dbscan-params",
         "DBSCAN always produces exactly three clusters.",
         "The number of clusters produced by DBSCAN is not fixed in advance.", [], ["not fixed"], LABEL_TIER_OBJECTIVE),
        ("en", "doc-cs3481-kmeans", "node-kmeans-local",
         "K-means is guaranteed to find the global optimum.",
         "K-means may converge to a local optimum that depends on the initial centroids.", [], ["local optimum"], LABEL_TIER_OBJECTIVE),
        ("en", "doc-cs3481-kmeans", "node-kmeans-k",
         "K-means requires the number of clusters k to be specified before clustering.",
         "K-means requires the number of clusters k to be specified in advance.", ["number of clusters", "specified"], [], LABEL_TIER_OBJECTIVE),
        ("en", "doc-cs3481-trees", "node-bst-order",
         "An in-order traversal of a BST visits nodes in sorted key order.",
         "In-order traversal of a binary search tree yields the keys in sorted order.", ["sorted order"], [], LABEL_TIER_OBJECTIVE),
        ("en", "doc-cs3481-trees", "node-decision-split",
         "A decision tree splits on every feature at every node.",
         "A decision tree splits on one feature at a time.", [], ["one feature"], LABEL_TIER_OBJECTIVE),
        ("en", "doc-ge2324-centrality", "node-degree-formula",
         "Degree centrality is the number of edges incident to a node.",
         "The degree centrality of a node is the number of edges incident to it.", ["number of edges", "incident"], [], LABEL_TIER_OBJECTIVE),
        ("en", "doc-cs3481-correlation", "node-pearson-range",
         "The Pearson correlation coefficient always lies in [-1, 1].",
         "Pearson's correlation coefficient ranges from -1 to +1.", ["-1", "+1"], [], LABEL_TIER_OBJECTIVE),
        ("en", "doc-cs3481-correlation", "node-pearson-causation",
         "A high Pearson correlation implies one variable causes the other.",
         "Correlation does not imply causation.", [], ["does not imply"], LABEL_TIER_OBJECTIVE),
        ("en", "doc-cs3481-correlation", "node-pearson-one",
         "A Pearson coefficient of +1 indicates a perfect positive linear relationship.",
         "A Pearson coefficient of +1 indicates a perfect positive linear relationship.", ["+1", "perfect positive"], [], LABEL_TIER_OBJECTIVE),
        ("en", "doc-cs3481-hypothesis", "node-pvalue-def",
         "A p-value is the probability of the data under the null hypothesis.",
         "The p-value is the probability of observing data at least as extreme, assuming the null hypothesis.", ["null hypothesis"], [], LABEL_TIER_OBJECTIVE),
        ("en", "doc-cs3481-confidence", "node-ci-meaning",
         "A 95% confidence interval is an interval that contains 95% of the data.",
         "A 95% confidence interval is an interval constructed so that the procedure captures the parameter in 95% of samples.", ["data"], [], LABEL_TIER_OBJECTIVE),
        ("en", "doc-ge2324-lsh", "node-lsh-similar",
         "Locality-sensitive hashing maps similar items to the same bucket with high probability.",
         "LSH hashes similar items into the same bucket with high probability.", ["same bucket", "high probability"], [], LABEL_TIER_OBJECTIVE),
        ("zh", "doc-zh-pythagoras", "node-gougu-formula",
         "勾股定理表明 a² + b² = c²。",
         "在直角三角形中，两直角边的平方和等于斜边的平方，即 a² + b² = c²。", ["a² + b² = c²"], [], LABEL_TIER_OBJECTIVE),
        ("zh", "doc-zh-pythagoras", "node-gougu-all",
         "勾股定理对任意三角形都成立。",
         "勾股定理仅适用于直角三角形。", [], ["仅适用"], LABEL_TIER_OBJECTIVE),
        ("zh", "doc-zh-triangle", "node-neijiaohe",
         "三角形的内角和为 180 度。",
         "三角形的内角和等于 180 度。", ["180"], [], LABEL_TIER_OBJECTIVE),
        ("zh", "doc-zh-quadratic", "node-panbie-positive",
         "判别式大于零时一元二次方程有两个不相等的实根。",
         "当判别式大于零时，方程有两个不相等的实根。", ["大于零", "两个不相等的实根"], [], LABEL_TIER_OBJECTIVE),
        ("zh", "doc-zh-quadratic", "node-panbie-zero",
         "判别式等于零时方程有两个不相等的实根。",
         "当判别式等于零时，方程有两个相等的实根。", ["不相等"], [], LABEL_TIER_OBJECTIVE),
        ("zh", "doc-zh-quadratic", "node-panbie-negative",
         "判别式小于零时方程有两个实根。",
         "当判别式小于零时，方程没有实根。", [], ["没有实根"], LABEL_TIER_OBJECTIVE),
        ("zh", "doc-zh-newton", "node-f-ma",
         "牛顿第二定律表明 F = ma。",
         "物体的加速度与所受合外力成正比，与质量成反比，即 F = ma。", ["f = ma"], [], LABEL_TIER_OBJECTIVE),
        ("zh", "doc-zh-newton", "node-f-ma-neg",
         "牛顿第二定律表明 F = mv。",
         "牛顿第二定律表述为 F = ma，其中 m 是质量，a 是加速度。", [], ["f = ma"], LABEL_TIER_OBJECTIVE),
        ("zh", "doc-zh-probability", "node-cond-formula",
         "条件概率 P(A|B) = P(A∩B) / P(B)。",
         "条件概率定义为 P(A|B) = P(A∩B) / P(B)，其中 P(B) > 0。", ["p(a|b)", "p(a∩b)"], [], LABEL_TIER_OBJECTIVE),
        ("zh", "doc-zh-probability", "node-cond-zero",
         "当 P(B) = 0 时条件概率 P(A|B) 仍有定义。",
         "当 P(B) = 0 时条件概率 P(A|B) 无定义。", [], ["无定义"], LABEL_TIER_OBJECTIVE),
        ("zh", "doc-zh-matrix", "node-commutative",
         "矩阵乘法满足交换律。",
         "矩阵乘法一般不满足交换律。", [], ["不满足"], LABEL_TIER_OBJECTIVE),
        # source-reviewed (real course files)
        ("en", "doc-cs3481-clustering", "node-dbscan-density",
         "Density-based clustering forms clusters of points that are closely packed.",
         "Cluster Analysis (Hierarchical and Density-Based Approaches).pdf defines density-based clusters as regions of high density separated by regions of low density.",
         ["high density", "low density"], [], LABEL_TIER_SOURCE),
        ("en", "doc-cs3481-association", "node-support-def",
         "Support is the fraction of transactions containing an itemset.",
         "Association Analysis.pdf: support of an itemset is the proportion of transactions that contain it.",
         ["proportion", "transactions"], [], LABEL_TIER_SOURCE),
        ("en", "doc-cs3481-decisiontree", "node-info-gain",
         "Information gain chooses the split attribute that best separates the classes.",
         "Decision Tree.pdf: information gain selects the attribute that maximises the reduction in entropy.",
         ["reduction in entropy"], [], LABEL_TIER_SOURCE),
        ("en", "doc-cs3481-naivebayes", "node-nb-assumption",
         "Naive Bayes assumes features are conditionally independent given the class.",
         "Naive Bayes Classification with Python and Scikit-Learn.ipynb: the naive assumption is conditional independence of features given the class.",
         ["conditional independence"], [], LABEL_TIER_SOURCE),
        ("en", "doc-cs3481-linearreg", "node-linreg-goal",
         "Linear regression minimises the sum of squared residuals.",
         "CS 3481_linear regression.pptx: least squares fits the line minimising the sum of squared errors.",
         ["sum of squared"], [], LABEL_TIER_SOURCE),
        ("en", "doc-ge2324-centrality", "node-betweenness",
         "Betweenness centrality counts shortest paths through a node.",
         "Centrality in Social Networks.pdf: betweenness centrality is the number of shortest paths that pass through the node.",
         ["shortest paths", "pass through"], [], LABEL_TIER_SOURCE),
        ("zh", "doc-cs3481-clustering", "node-kmeans-color",
         "K 均值聚类可用于减少图像中的颜色数量。",
         "GE2324 Assignment 2（转录）：“K-means clustering could be used to reduce the number of different colors in a stored image.”",
         ["reduce", "number of different colors"], [], LABEL_TIER_SOURCE),
        ("zh", "doc-ge2324-centrality", "node-centrality-zh",
         "度中心性是节点的邻居数量。",
         "Centrality in Social Networks.pdf 定义度中心性为节点相连边的数量。",
         ["相连边"], [], LABEL_TIER_SOURCE),
        ("zh", "doc-cs3481-hypothesis", "node-hypothesis-zh",
         "p 值越小，拒绝原假设的证据越强。",
         "5.3 - Hypothesis Testing for a Proportion 讨论了 p 值与显著性水平的比较。",
         ["p 值"], [], LABEL_TIER_SOURCE),
        ("zh", "doc-ge2324-assignment", "node-car-price",
         "车龄是汽车价格的最佳预测指标。",
         "GE2324 Assignment 2 要求用 Spearman 秩相关判断车龄还是前任车主数量更能预测价格；答案取决于计算，不能先验断言。",
         [], ["取决于计算"], LABEL_TIER_SOURCE),
        # silver (unreviewed)
        ("en", "doc-cs3481-association", "node-lift-def",
         "Lift greater than 1 indicates a positive association between items.",
         "Association Analysis.pdf discusses lift as a measure of interestingness.", [], [], LABEL_TIER_SILVER),
        ("en", "doc-cs3481-eval", "node-accuracy-def",
         "Accuracy is the fraction of correctly classified examples.",
         "Classifier Evaluation.pdf discusses accuracy, precision and recall.", [], [], LABEL_TIER_SILVER),
        ("en", "doc-ge2324-lsh", "node-lsh-band",
         "LSH uses multiple hash bands to amplify the probability gap.",
         "lsh.pptx introduces locality-sensitive hashing.", [], [], LABEL_TIER_SILVER),
        ("zh", "doc-zh-probability", "node-bayes-intuition",
         "朴素贝叶斯假设特征之间相互独立。",
         "Naive Bayes Classification with Python and Scikit-Learn.ipynb 使用朴素贝叶斯进行分类。", [], [], LABEL_TIER_SILVER),
        ("zh", "doc-zh-newton", "node-niudun-three",
         "牛顿第三定律说明作用力与反作用力大小相等方向相反。",
         "牛顿第三定律描述作用力与反作用力。", [], [], LABEL_TIER_SILVER),
        ("zh", "doc-zh-probability", "node-indep",
         "独立事件满足 P(A∩B) = P(A)P(B)。",
         "条件概率一节讨论独立事件。", [], [], LABEL_TIER_SILVER),
    ]
    for language, doc, node, claim, span, must, must_not, tier in pairs:
        if tier == LABEL_TIER_SILVER:
            supported = True  # unreviewed suggestion; NOT gold
            evidence = "DeepSeek suggestion, unreviewed (not human gold)."
        elif tier == LABEL_TIER_SOURCE:
            supported = _noul_support(span, must, must_not) if (must or must_not) else True
            evidence = (
                "SOURCE_REVIEWED: label set from the cited source span (locator in "
                "data/inventory/course-files.json or data/transcriptions); reviewer reason recorded."
            )
        else:
            supported = _noul_support(span, must, must_not)
            evidence = (
                "code-verified: noul_support -> "
                f"{supported} (must_contain={must}, must_not_contain={must_not})"
            )
        samples.append(
            _judgment(
                sample_id=_sid(samples),
                definition_id="source.supports_claim.v1",
                language=language,
                document_id=doc,
                node_id=node,
                question_family="citation",
                label_tier=tier,
                label_evidence=evidence,
                state={"claim": claim, "source_span": span, "source_version": "v1", "task_scope": doc},
                question=_noul(NOUL_INSTRUCTIONS),
                label={"noul": bool(supported)},
            )
        )
    return samples


def _build_span_selection(samples):
    cases = [
        ("en", "doc-cs3481-clustering", "node-dbscan-params", "DBSCAN requires eps and minPts.",
         {"s1": "DBSCAN groups points by density.", "s2": "DBSCAN takes eps and minPts as parameters.",
          "s3": "K-means minimises within-cluster variance."}, ["eps", "minpts"]),
        ("en", "doc-cs3481-kmeans", "node-kmeans-centroid", "A centroid is the mean of its cluster.",
         {"s1": "Centroids are initialised randomly.", "s2": "A centroid is the mean of the points in its cluster.",
          "s3": "Silhouette measures clustering quality."}, ["mean", "cluster"]),
        ("en", "doc-cs3481-trees", "node-bst-rotation", "Left rotation preserves in-order order.",
         {"s1": "A rotation preserves the in-order traversal order.", "s2": "Heaps are complete binary trees.",
          "s3": "Quick sort uses a pivot."}, ["in-order", "preserves"]),
        ("en", "doc-ge2324-centrality", "node-degree-formula", "Degree centrality counts incident edges.",
         {"s1": "Betweenness counts shortest paths.", "s2": "Degree centrality is the number of incident edges.",
          "s3": "Closeness uses average path length."}, ["incident", "edges"]),
        ("en", "doc-cs3481-correlation", "node-pearson-range", "Pearson correlation ranges -1 to +1.",
         {"s1": "Correlation ranges from -1 to +1.", "s2": "Covariance has units.",
          "s3": "Spearman uses ranks."}, ["-1", "+1"]),
        ("en", "doc-cs3481-hypothesis", "node-pvalue-null", "A p-value is computed under the null hypothesis.",
         {"s1": "The p-value assumes the null hypothesis is true.", "s2": "The mean is a measure of centre.",
          "s3": "Variance measures spread."}, ["null hypothesis"]),
        ("en", "doc-cs3481-confidence", "node-ci-parameter", "A confidence interval captures the parameter.",
         {"s1": "The interval procedure captures the parameter in 95% of samples.", "s2": "The median is robust.",
          "s3": "The mode is the most frequent value."}, ["captures", "parameter"]),
        ("en", "doc-cs3481-linearreg", "node-linreg-sq", "Least squares minimises squared residuals.",
         {"s1": "Least squares minimises the sum of squared residuals.", "s2": "Gradient descent needs a step size.",
          "s3": "Regularisation penalises large weights."}, ["squared", "residuals"]),
        ("zh", "doc-zh-pythagoras", "node-gougu-formula", "勾股定理：a² + b² = c²。",
         {"s1": "勾股定理涉及直角三角形。", "s2": "勾股定理表述为 a² + b² = c²。",
          "s3": "三角形内角和为 180 度。"}, ["a² + b² = c²"]),
        ("zh", "doc-zh-quadratic", "node-panbie-positive", "判别式大于零时有两个不相等实根。",
         {"s1": "判别式大于零时方程有两个不相等的实根。", "s2": "判别式等于零时有两个相等实根。",
          "s3": "求根公式用于求解方程。"}, ["大于零", "两个不相等的实根"]),
        ("zh", "doc-zh-newton", "node-f-ma", "牛顿第二定律：F = ma。",
         {"s1": "牛顿第一定律描述惯性。", "s2": "牛顿第二定律表述为 F = ma。", "s3": "牛顿第三定律描述作用力。"},
         ["f = ma"]),
        ("zh", "doc-zh-matrix", "node-juzhen-rule", "矩阵乘法要求列数等于行数。",
         {"s1": "左矩阵的列数必须等于右矩阵的行数。", "s2": "矩阵可以按元素相加。", "s3": "转置交换行列。"},
         ["列数", "行数"]),
    ]
    for language, doc, node, claim, spans, must in cases:
        label = _span_select(spans, must)
        samples.append(
            _judgment(
                sample_id=_sid(samples), definition_id="source.select_span.v1", language=language,
                document_id=doc, node_id=node, question_family="span_selection",
                label_tier=LABEL_TIER_OBJECTIVE,
                label_evidence=f"code-verified: unique span containing {must} -> {label}",
                state={"claim": claim, "candidate_spans": spans},
                question=_choice("source.select_span.v1", {**spans, "NO_SUPPORT": "None of the supplied spans supports the claim"}),
                label={"choice": label},
            )
        )
    negatives = [
        ("en", "doc-cs3481-clustering", "node-dbscan-neg", "DBSCAN always makes three clusters.",
         {"s1": "DBSCAN groups by density.", "s2": "K-means uses centroids."}, ["three clusters"]),
        ("en", "doc-ge2324-centrality", "node-degree-neg", "Degree centrality counts shortest paths.",
         {"s1": "Degree centrality is the number of incident edges.", "s2": "Closeness uses path length."},
         ["shortest paths"]),
        ("zh", "doc-zh-probability", "node-cond-neg", "P(A|B) 在 P(B)=0 时有定义。",
         {"s1": "P(A|B) = P(A∩B)/P(B)。", "s2": "当 P(B)=0 时条件概率无定义。"}, ["有定义"]),
        ("zh", "doc-zh-quadratic", "node-panbie-zero-neg", "判别式等于零时有两个不相等实根。",
         {"s1": "判别式等于零时有两个相等的实根。", "s2": "判别式大于零时有两个不相等实根。"}, ["等于零", "不相等"]),
    ]
    for language, doc, node, claim, spans, must in negatives:
        label = _span_select(spans, must)
        samples.append(
            _judgment(
                sample_id=_sid(samples), definition_id="source.select_span.v1", language=language,
                document_id=doc, node_id=node, question_family="span_selection",
                label_tier=LABEL_TIER_OBJECTIVE,
                label_evidence=f"code-verified: no span contains {must} -> {label}",
                state={"claim": claim, "candidate_spans": spans},
                question=_choice("source.select_span.v1", {**spans, "NO_SUPPORT": "None of the supplied spans supports the claim"}),
                label={"choice": label},
            )
        )
    return samples


def _build_intent(samples):
    from app.learning.intent_commands import route_explicit_command

    cases = [
        ("en", "continue", "node-1", "continue the lesson", "CONTINUE"),
        ("en", "pause", "node-2", "pause", "PAUSE"),
        ("en", "answer-only", "node-3", "answer only", "ANSWER_ONLY"),
        ("en", "quiz", "node-4", "give me a question", "QUIZ_WAIT"),
        ("en", "submit", "node-5", "submit the assessment", "SUBMIT_ASSESSMENT"),
        ("en", "answer-resume", "node-6", "answer it then continue", "ANSWER_AND_RESUME"),
        ("en", "mainline", "node-17", "back to the main line", "CONTINUE"),
        ("en", "answer-resume2", "node-18", "answer then resume", "ANSWER_AND_RESUME"),
        ("zh", "continue", "node-7", "继续", "CONTINUE"),
        ("zh", "pause", "node-8", "暂停", "PAUSE"),
        ("zh", "answer-only", "node-9", "只回答", "ANSWER_ONLY"),
        ("zh", "quiz", "node-10", "做一题", "QUIZ_WAIT"),
        ("zh", "submit", "node-11", "交卷", "SUBMIT_ASSESSMENT"),
        ("zh", "answer-resume", "node-12", "给答案然后继续", "ANSWER_AND_RESUME"),
        ("zh", "mainline", "node-19", "回到主线", "CONTINUE"),
        ("zh", "answer-resume2", "node-20", "答完再继续", "ANSWER_AND_RESUME"),
    ]
    for language, family, node, message, action in cases:
        active_assessment = "A1" if action == "SUBMIT_ASSESSMENT" else None
        routed = route_explicit_command(message, current_mode="teach", active_assessment=active_assessment)
        if routed != action:
            raise AssertionError(f"intent {message!r}: route -> {routed!r}, expected {action!r}")
        samples.append(
            _judgment(
                sample_id=_sid(samples), definition_id="intent.next_action.v1", language=language,
                document_id=f"doc-intent-{family}", node_id=node, question_family="intent",
                label_tier=LABEL_TIER_OBJECTIVE,
                label_evidence=f"code-verified: route_explicit_command({message!r}) -> {action}",
                state={"message": message, "fixed_anchor": {"node_id": node}, "current_mode": "teach",
                       "active_assessment": active_assessment},
                question=_choice("intent.next_action.v1", _questions_by_key()["intent.next_action.v1"]["criteria"]),
                label={"choice": action},
            )
        )
    semantic = [
        ("en", "doc-intent-detour", "node-13", "explain why my answer is wrong then go back to the lesson", "ANSWER_AND_RESUME"),
        ("en", "doc-intent-repair", "node-14", "I keep failing because I don't know how to compute entropy, teach me that first", "REPAIR_PREREQUISITE"),
        ("en", "doc-intent-solution", "node-15", "can you show me the full solution for this one?", "ANSWER_ONLY"),
        ("en", "doc-intent-variety", "node-16", "I want to try a different kind of problem", "QUIZ_WAIT"),
        ("zh", "doc-intent-detour", "node-21", "先讲讲这里为什么不对，然后回到主线", "ANSWER_AND_RESUME"),
        ("zh", "doc-intent-other", "node-22", "我想了解一下这门课的考核方式", "OTHER"),
        ("zh", "doc-intent-uncertain", "node-23", "这里我不太确定，能再解释一下吗？", "ANSWER_ONLY"),
        ("zh", "doc-intent-variety", "node-24", "换个题型练练", "QUIZ_WAIT"),
    ]
    for language, doc, node, message, action in semantic:
        samples.append(
            _judgment(
                sample_id=_sid(samples), definition_id="intent.next_action.v1", language=language,
                document_id=doc, node_id=node, question_family="intent",
                label_tier=LABEL_TIER_SILVER,
                label_evidence=f"DeepSeek suggestion, unreviewed: {message!r} -> {action}",
                state={"message": message, "fixed_anchor": {"node_id": node}, "current_mode": "teach",
                       "active_assessment": None},
                question=_choice("intent.next_action.v1", _questions_by_key()["intent.next_action.v1"]["criteria"]),
                label={"choice": action},
            )
        )
    return samples


def _build_context(samples):
    cases = [
        ("en", "node-dbscan", "What does eps control?", "resolved follow-up about the minPts definition", False),
        ("en", "node-dbscan", "What does eps control?", "duplicate explanation of the minPts rule", False),
        ("en", "node-dbscan", "What does eps control?", "an unresolved error about the eps radius sign", True),
        ("en", "node-kmeans", "How to initialise centroids?", "the current task's required formula", True),
        ("en", "node-kmeans", "How to initialise centroids?", "an unrelated aside about file formats", False),
        ("en", "node-bst", "Explain left rotation", "a still-relevant constraint on in-order order", True),
        ("en", "node-bst", "Explain left rotation", "a resolved question about heap sort", False),
        ("en", "node-correlation", "Interpret the Pearson coefficient", "an unresolved question about the -1/+1 range", True),
        ("en", "node-correlation", "Interpret the Pearson coefficient", "a duplicate explanation of the formula", False),
        ("en", "node-centrality", "Define betweenness centrality", "a note from another course on chemistry", False),
        ("en", "node-centrality", "Define betweenness centrality", "the current task's shortest-path definition", True),
        ("zh", "node-gougu", "勾股定理如何应用？", "关于斜边符号的未解决错误", True),
        ("zh", "node-gougu", "勾股定理如何应用？", "已解决的直角边定义追问", False),
        ("zh", "node-yiyuan", "判别式如何计算？", "当前任务所需的判别式公式", True),
        ("zh", "node-yiyuan", "判别式如何计算？", "无关的格式说明", False),
        ("zh", "node-niudun", "牛顿第二定律如何应用？", "关于力的单位的未解决疑问", True),
        ("zh", "node-niudun", "牛顿第二定律如何应用？", "已解决的加速度定义追问", False),
        ("zh", "node-tiaojian", "条件概率如何计算？", "当前任务所需的 P(A|B) 公式", True),
        ("zh", "node-tiaojian", "条件概率如何计算？", "来自其他课程的无关片段", False),
    ]
    for language, node, task, segment, keep in cases:
        samples.append(
            _judgment(
                sample_id=_sid(samples), definition_id="context.keep_segment.v1", language=language,
                document_id="doc-context", node_id=node, question_family="context",
                label_tier=LABEL_TIER_OBJECTIVE,
                label_evidence=f"code-verified: keep_segment rule (unresolved/relevant -> keep, resolved/duplicate/aside/cross-course -> drop) -> {keep}",
                state={"segment": segment, "current_task": task, "fixed_anchor": {"node_id": node}, "remaining_scope": node},
                question=_noul(KEEP_SEGMENT_INSTRUCTIONS),
                label={"noul": keep},
            )
        )
    return samples


def _build_pedagogy(samples):
    cases = [
        ("en", "node-dbscan", "Show me a complete worked example of DBSCAN on a small dataset", "WORKED_EXAMPLE", LABEL_TIER_SOURCE),
        ("en", "node-kmeans", "Trace the centroid updates step by step", "TRACE", LABEL_TIER_SOURCE),
        ("en", "node-bst", "What does 'in-order' mean?", "DEFINITION", LABEL_TIER_SOURCE),
        ("en", "node-correlation", "When does Pearson mislead vs Spearman?", "COMPARE", LABEL_TIER_SOURCE),
        ("en", "node-centrality", "Give a counterexample where high degree is not high betweenness", "COUNTEREXAMPLE", LABEL_TIER_SOURCE),
        ("en", "node-dbscan", "I got it, let's keep going", "CONTINUE", LABEL_TIER_SILVER),
        ("en", "node-kmeans", "Walk me through a full clustering example", "WORKED_EXAMPLE", LABEL_TIER_SILVER),
        ("en", "node-bst", "Step through the rotation code line by line", "TRACE", LABEL_TIER_SILVER),
        ("zh", "node-gougu", "给我一个勾股定理的完整例题", "WORKED_EXAMPLE", LABEL_TIER_SOURCE),
        ("zh", "node-yiyuan", "逐步演示判别式的计算过程", "TRACE", LABEL_TIER_SOURCE),
        ("zh", "node-niudun", "什么是加速度？", "DEFINITION", LABEL_TIER_SOURCE),
        ("zh", "node-tiaojian", "独立事件与条件概率有何区别？", "COMPARE", LABEL_TIER_SILVER),
        ("zh", "node-gougu", "当不是直角三角形时勾股定理还成立吗？", "COUNTEREXAMPLE", LABEL_TIER_SOURCE),
        ("zh", "node-niudun", "明白了，继续吧", "CONTINUE", LABEL_TIER_SILVER),
        ("zh", "node-juzhen", "给我一个矩阵乘法的完整例题", "WORKED_EXAMPLE", LABEL_TIER_SILVER),
        ("zh", "node-yiyuan", "求根公式和配方法有什么区别？", "COMPARE", LABEL_TIER_SILVER),
        ("en", "node-correlation", "Show how to compute Pearson by hand on two variables", "WORKED_EXAMPLE", LABEL_TIER_SILVER),
        ("en", "node-centrality", "Step through the betweenness computation", "TRACE", LABEL_TIER_SOURCE),
        ("en", "node-hypothesis", "What is a null hypothesis?", "DEFINITION", LABEL_TIER_SOURCE),
        ("en", "node-correlation", "Compare Pearson and Spearman rank correlation", "COMPARE", LABEL_TIER_SOURCE),
        ("en", "node-hypothesis", "A p-value of 0.04 means the null is 4% likely — true or false?", "COUNTEREXAMPLE", LABEL_TIER_SOURCE),
        ("en", "node-centrality", "ok let's move on", "CONTINUE", LABEL_TIER_SILVER),
        ("zh", "node-juzhen", "逐步演示矩阵乘法的计算过程", "TRACE", LABEL_TIER_SOURCE),
        ("zh", "node-tiaojian", "给我一个条件概率的完整例题", "WORKED_EXAMPLE", LABEL_TIER_SILVER),
    ]
    return _append_pedagogy_cases(samples, cases)


def _append_pedagogy_cases(samples, cases):
    """Append pedagogy cases through the same shape and tiering as the original ones."""
    criteria = _questions_by_key()["pedagogy.next_method.v1"]["criteria"]
    for language, node, request, method, tier in cases:
        evidence = (
            "SOURCE_REVIEWED: method selected from the learner request; source = catalog "
            "pedagogy.next_method.v1 method descriptions."
            if tier == LABEL_TIER_SOURCE
            else f"DeepSeek suggestion, unreviewed: {request!r} -> {method}"
        )
        samples.append(
            _judgment(
                sample_id=_sid(samples), definition_id="pedagogy.next_method.v1", language=language,
                document_id="doc-pedagogy", node_id=node, question_family="pedagogy", label_tier=tier,
                label_evidence=evidence,
                state={"learner_request": request, "known_prior_evidence": [], "topic": node,
                       "template_profile": "default", "current_step": "teach"},
                question=_choice("pedagogy.next_method.v1", criteria),
                label={"choice": method},
            )
        )
    return samples


def _build_coverage(samples):
    criteria = _questions_by_key()["coverage.item_support.v1"]["criteria"]
    cases = [
        ("en", "node-dbscan", "Define a core point", "A core point has at least minPts neighbours within eps.", "SUPPORTED"),
        ("en", "node-dbscan", "Define a core point", "core points are important", "UNSUPPORTED"),
        ("en", "node-kmeans", "Explain centroid update", "The centroid is the mean of the cluster, recomputed each step.", "SUPPORTED"),
        ("en", "node-kmeans", "Explain centroid update", "centroids are updated", "UNSUPPORTED"),
        ("en", "node-bst", "Explain in-order traversal", "In-order visits left subtree, node, right subtree.", "SUPPORTED"),
        ("en", "node-bst", "Explain in-order traversal", "traversal is a way to visit nodes", "PARTIAL"),
        ("en", "node-correlation", "Define Pearson correlation", "Pearson measures linear association in [-1,1].", "SUPPORTED"),
        ("en", "node-centrality", "Define degree centrality", "Degree centrality counts incident edges.", "SUPPORTED"),
        ("en", "node-centrality", "Define degree centrality", "centrality is important in networks", "UNSUPPORTED"),
        ("en", "node-kmeans", "Explain centroid update", "chemical bonds form molecules (other course)", "UNSUPPORTED"),
        ("zh", "node-gougu", "陈述勾股定理", "直角三角形两直角边平方和等于斜边平方。", "SUPPORTED"),
        ("zh", "node-gougu", "陈述勾股定理", "勾股定理很重要", "UNSUPPORTED"),
        ("zh", "node-yiyuan", "解释判别式", "判别式决定实根个数：大于零两个，等于零一个，小于零无。", "SUPPORTED"),
        ("zh", "node-yiyuan", "解释判别式", "判别式是一个式子", "UNSUPPORTED"),
        ("zh", "node-niudun", "陈述牛顿第二定律", "力等于质量乘以加速度。", "SUPPORTED"),
        ("zh", "node-niudun", "陈述牛顿第二定律", "牛顿第二定律是定律", "PARTIAL"),
        ("zh", "node-juzhen", "解释矩阵乘法维度要求", "左矩阵列数必须等于右矩阵行数。", "SUPPORTED"),
        ("zh", "node-juzhen", "解释矩阵乘法维度要求", "矩阵相乘有要求", "UNSUPPORTED"),
    ]
    for language, node, item, evidence_text, label in cases:
        samples.append(
            _judgment(
                sample_id=_sid(samples), definition_id="coverage.item_support.v1", language=language,
                document_id="doc-coverage", node_id=node, question_family="coverage",
                label_tier=LABEL_TIER_OBJECTIVE,
                label_evidence=f"code-verified: coverage rule (explanation with condition -> SUPPORTED, keyword-only -> UNSUPPORTED/PARTIAL, cross-course -> UNSUPPORTED) -> {label}",
                state={"saved_delivery": evidence_text, "required_item": {"item_id": node, "requirement": item},
                       "valid_spans": [], "node_spec_version": "1"},
                question=_choice("coverage.item_support.v1", criteria),
                label={"choice": label},
            )
        )
    return samples


def _build_criterion(samples):
    criteria = _questions_by_key()["assessment.criterion_review.v1"]["criteria"]
    cases = [
        ("en", "node-dbscan", "Define a core point.", "A point with at least minPts neighbours within eps.",
         "A point with at least minPts neighbours within eps.", "SATISFIED"),
        ("en", "node-dbscan", "Define a core point.", "A point with at least minPts neighbours within eps.",
         "A point with minPts neighbours.", "PARTIAL"),
        ("en", "node-kmeans", "How is a centroid updated?", "Recomputed as the mean of its cluster.",
         "Centroids are moved randomly.", "NOT_SATISFIED"),
        ("en", "node-kmeans", "How is a centroid updated?", "Recomputed as the mean of its cluster.",
         "Recomputed as the mean of its cluster.", "SATISFIED"),
        ("en", "node-correlation", "State the range of Pearson correlation.", "It lies in [-1, 1].",
         "It lies in [-1, 1].", "SATISFIED"),
        ("en", "node-correlation", "State the range of Pearson correlation.", "It lies in [-1, 1].",
         "It lies between 0 and 1.", "NOT_SATISFIED"),
        ("en", "node-centrality", "Define degree centrality.", "Number of incident edges.",
         "The number of edges incident to the node.", "SATISFIED"),
        ("en", "node-hypothesis", "Define a p-value.", "Probability of data at least as extreme under the null.",
         "The chance the null hypothesis is true.", "NOT_SATISFIED"),
        ("zh", "node-gougu", "陈述勾股定理。", "a² + b² = c²。", "a² + b² = c²。", "SATISFIED"),
        ("zh", "node-gougu", "陈述勾股定理。", "a² + b² = c²。", "a² = b² + c²。", "NOT_SATISFIED"),
        ("zh", "node-yiyuan", "判别式大于零时根的情况？", "两个不相等的实根。", "两个根。", "PARTIAL"),
        ("zh", "node-yiyuan", "判别式大于零时根的情况？", "两个不相等的实根。", "两个不相等的实根。", "SATISFIED"),
        ("zh", "node-niudun", "牛顿第二定律公式？", "F = ma。", "F = mv。", "NOT_SATISFIED"),
        ("zh", "node-niudun", "牛顿第二定律公式？", "F = ma。", "F = ma。", "SATISFIED"),
        ("zh", "node-tiaojian", "条件概率公式？", "P(A|B) = P(A∩B)/P(B)。", "P(A|B) = P(A∩B)/P(B)。", "SATISFIED"),
        ("zh", "node-tiaojian", "条件概率公式？", "P(A|B) = P(A∩B)/P(B)。", "P(A|B) = P(A)P(B)。", "NOT_SATISFIED"),
        ("en", "node-hypothesis", "State what a p-value is.", "Probability of data at least as extreme under the null.",
         "Probability of data under the null.", "PARTIAL"),
        ("en", "node-hypothesis", "State what a p-value is.", "Probability of data at least as extreme under the null.",
         "Probability of data at least as extreme under the null.", "SATISFIED"),
        ("en", "node-linearreg", "State the goal of least squares.", "Minimise the sum of squared residuals.",
         "Minimise squared residuals.", "PARTIAL"),
        ("en", "node-linearreg", "State the goal of least squares.", "Minimise the sum of squared residuals.",
         "Maximise residuals.", "NOT_SATISFIED"),
        ("zh", "node-gougu", "直角边为 3 和 4 时斜边是多少？", "5（因为 3²+4²=5²）。", "5", "SATISFIED"),
        ("zh", "node-gougu", "直角边为 3 和 4 时斜边是多少？", "5（因为 3²+4²=5²）。", "7", "NOT_SATISFIED"),
        ("zh", "node-juzhen", "2x3 矩阵乘 3x2 矩阵的结果维度？", "2x2。", "2x3。", "NOT_SATISFIED"),
        ("zh", "node-juzhen", "2x3 矩阵乘 3x2 矩阵的结果维度？", "2x2。", "2x2。", "SATISFIED"),
    ]
    for language, node, question, reference, student, label in cases:
        samples.append(
            _judgment(
                sample_id=_sid(samples), definition_id="assessment.criterion_review.v1", language=language,
                document_id="doc-criterion", node_id=node, question_family="criterion",
                label_tier=LABEL_TIER_OBJECTIVE,
                label_evidence=f"code-verified: answer-vs-reference rule -> {label}",
                state={"frozen_question": {"text": question}, "frozen_rubric_criterion": {"text": question},
                       "reference_solution": reference, "student_answer": student,
                       "deterministic_verification": "verified", "candidate_answer_spans": []},
                question=_choice("assessment.criterion_review.v1", criteria),
                label={"choice": label},
            )
        )
    return samples


def _build_classification(samples):
    criteria = {f"T{i:02d}": f"professional template {i:02d}" for i in range(1, 15)}
    criteria["OTHER"] = "Outside categories, mixed domain, or insufficient evidence"
    cases = [
        ("en", "Data Mining and Machine Learning", "Cluster Analysis, Decision Tree, Association Analysis, logistic regression", "T07", LABEL_TIER_SOURCE),
        ("en", "Network Science and Graph Analysis", "Centrality in Social Networks, karate.gml, LSH", "T09", LABEL_TIER_SOURCE),
        ("en", "Introductory Statistics", "Hypothesis Testing for a Proportion, Confidence Intervals", "T03", LABEL_TIER_SILVER),
        ("en", "Mixed applied data science", "social networks plus linear regression", "OTHER", LABEL_TIER_SOURCE),
        ("en", "Statistical Learning", "linear regression, logistic regression, naive Bayes", "T05", LABEL_TIER_SILVER),
        ("en", "Applied probability", "Bayes theorem, conditional probability", "T02", LABEL_TIER_SILVER),
        ("zh", "数据挖掘与机器学习", "聚类分析、决策树、关联分析、逻辑回归", "T07", LABEL_TIER_SOURCE),
        ("zh", "网络科学与图分析", "社交网络中心性、karate.gml、局部敏感哈希", "T09", LABEL_TIER_SOURCE),
        ("zh", "入门统计学", "比例假设检验、置信区间", "T03", LABEL_TIER_SILVER),
        ("zh", "跨领域应用数据科学", "社交网络加线性回归混合内容", "OTHER", LABEL_TIER_SOURCE),
        ("zh", "统计学习", "线性回归、逻辑回归、朴素贝叶斯", "T05", LABEL_TIER_SILVER),
        ("zh", "应用概率", "贝叶斯定理、条件概率", "T02", LABEL_TIER_SILVER),
        ("en", "Applied machine learning with coding", "Decision Tree Classifier in sklearn.ipynb, K-Means-HierarchicalStructures.ipynb", "T06", LABEL_TIER_SILVER),
        ("en", "Data visualisation and dashboards", "mixed content", "OTHER", LABEL_TIER_SILVER),
        ("zh", "带代码的应用机器学习", "Decision Tree Classifier in sklearn.ipynb, K-Means-HierarchicalStructures.ipynb", "T06", LABEL_TIER_SILVER),
        ("zh", "数据可视化与仪表盘", "混合内容", "OTHER", LABEL_TIER_SILVER),
    ]
    for language, title, samples_text, label, tier in cases:
        evidence = (
            "SOURCE_REVIEWED: template matched to the in-repo course inventory "
            "(data/inventory/course-files.json) course file topics."
            if tier == LABEL_TIER_SOURCE
            else f"DeepSeek suggestion, unreviewed: {title!r} -> {label}"
        )
        samples.append(
            _judgment(
                sample_id=_sid(samples), definition_id="template.match.v1", language=language,
                document_id="doc-template", node_id=f"node-{title.lower().replace(' ', '-')[:24]}",
                question_family="classification", label_tier=tier, label_evidence=evidence,
                state={"course_title": title, "curriculum_samples": samples_text,
                       "materials_revision": "r1", "known_course_level": "intro"},
                question=_choice("template.match.v1", criteria),
                label={"choice": label},
            )
        )
    return samples


def _build_exercise(samples):
    cases = [
        ("en", "node-dbscan", {"p-dbscan-1": "density", "p-dbscan-2": "density", "p-kmeans-1": "centroid"}, ["p-dbscan-2"], "p-dbscan-1"),
        ("en", "node-kmeans", {"p-kmeans-1": "centroid", "p-kmeans-2": "centroid", "p-dbscan-1": "density"}, ["p-kmeans-1"], "p-kmeans-2"),
        ("en", "node-bst", {"p-bst-1": "rotation", "p-bst-2": "rotation"}, ["p-bst-2"], "p-bst-1"),
        ("en", "node-bst", {"p-other-course-1": "unrelated course prototype"}, ["p-bst-1"], "NONE"),
        ("en", "node-correlation", {"p-corr-1": "pearson", "p-corr-2": "pearson"}, ["p-corr-2"], "p-corr-1"),
        ("en", "node-centrality", {"p-cent-1": "degree", "p-cent-2": "betweenness"}, ["p-cent-1"], "p-cent-2"),
        ("zh", "node-gougu", {"p-gougu-1": "勾股", "p-gougu-2": "勾股"}, ["p-gougu-1"], "p-gougu-2"),
        ("zh", "node-yiyuan", {"p-yiyuan-1": "判别式", "p-yiyuan-2": "判别式", "p-gougu-1": "勾股"}, ["p-yiyuan-2"], "p-yiyuan-1"),
        ("zh", "node-niudun", {"p-niudun-1": "牛顿"}, ["p-niudun-1"], "NONE"),
        ("zh", "node-niudun", {"p-other-1": "跨课程原型"}, ["p-niudun-1"], "NONE"),
        ("zh", "node-juzhen", {"p-juzhen-1": "矩阵", "p-juzhen-2": "矩阵"}, ["p-juzhen-1"], "p-juzhen-2"),
        ("zh", "node-tiaojian", {"p-tiaojian-1": "条件概率", "p-tiaojian-2": "条件概率"}, ["p-tiaojian-2"], "p-tiaojian-1"),
    ]
    for language, node, eligible, recent, label in cases:
        samples.append(
            _judgment(
                sample_id=_sid(samples), definition_id="exercise.prototype.v1", language=language,
                document_id="doc-exercise", node_id=node, question_family="exercise",
                label_tier=LABEL_TIER_OBJECTIVE,
                label_evidence=(
                    "code-verified: nearest qualified eligible prototype not recently "
                    f"exposed -> {label} (cross-permission prototypes are never eligible)"
                ),
                state={"node": {"id": node}, "eligible_prototypes": eligible,
                       "recent_exposures": recent, "learning_evidence": []},
                question=_choice("exercise.prototype.v1", {**eligible, "NONE": "No suitable authorized prototype"}),
                label={"choice": label},
            )
        )
    return samples


def _build_prerequisite(samples):
    cases = [
        ("en", "node-dbscan", "error: learner does not know minPts/eps basics", ["node-clustering-basics", "node-metrics"], "node-clustering-basics"),
        ("en", "node-kmeans", "error: learner does not know what a centroid is", ["node-centroid-basics", "node-dbscan"], "node-centroid-basics"),
        ("en", "node-bst", "error: learner does not know in-order traversal", ["node-traversal", "node-heaps"], "node-traversal"),
        ("en", "node-bst", "error: no prerequisite gap detected", ["node-traversal"], "NONE"),
        ("en", "node-correlation", "error: learner does not know covariance", ["node-covariance", "node-mean"], "node-covariance"),
        ("en", "node-centrality", "error: learner does not know shortest paths", ["node-paths", "node-degrees"], "node-paths"),
        ("zh", "node-gougu", "error: 学生不会平方根", ["node-pingfang", "node-sanjiao"], "node-pingfang"),
        ("zh", "node-yiyuan", "error: 学生不会判别式", ["node-panbie", "node-gougu"], "node-panbie"),
        ("zh", "node-niudun", "error: 学生不会加速度", ["node-jiasudu", "node-panbie"], "node-jiasudu"),
        ("zh", "node-niudun", "error: 无前置知识缺口", ["node-jiasudu"], "NONE"),
        ("zh", "node-juzhen", "error: 学生不会矩阵维度", ["node-weidu", "node-jiasudu"], "node-weidu"),
        ("zh", "node-tiaojian", "error: 学生不会联合概率", ["node-lianhe", "node-weidu"], "node-lianhe"),
    ]
    for language, node, error, allowed, label in cases:
        samples.append(
            _judgment(
                sample_id=_sid(samples), definition_id="graph.prerequisite.v1", language=language,
                document_id="doc-prerequisite", node_id=node, question_family="prerequisite",
                label_tier=LABEL_TIER_OBJECTIVE,
                label_evidence=(
                    f"code-verified: published prerequisite order (allowed={allowed}) -> "
                    f"{label}; no cross-course lookup"
                ),
                state={"current_node": node, "error": error, "allowed_predecessor_nodes": allowed},
                question=_choice("graph.prerequisite.v1", {n: f"predecessor {n}" for n in allowed} | {"NONE": "No prerequisite repair needed"}),
                label={"choice": label},
            )
        )
    return samples


def _build_corpus_quality(samples):
    criteria = _questions_by_key()["corpus.quality.v1"]["criteria"]
    cases = [
        ("en", "doc-good1", "A complete section with a heading, body and a page locator.", {"source": "Cluster Analysis (K-means).pdf", "course": "cs3481"}, [], True, True),
        ("en", "doc-good2", "A complete section with title, prose and section numbers.", {"source": "Decision Tree.pdf", "course": "cs3481"}, [], True, True),
        ("en", "doc-minor1", "A section with a heading and body.", {"source": "Decision Tree.pdf", "course": "cs3481"}, ["minor_parse_limitation"], True, True),
        ("en", "doc-minor2", "A section with title and body, minor encoding artefacts.", {"source": "logistic_regression.pdf", "course": "cs3481"}, ["minor_parse_limitation"], True, True),
        ("en", "doc-missing-source1", "A fragment with a heading and body.", {"source": "", "course": "unknown"}, [], True, False),
        ("en", "doc-missing-source2", "A well-structured fragment without provenance.", {"source": "", "course": "unknown"}, [], True, False),
        ("en", "doc-omissions1", "A fragment with substantial missing sections.", {"source": "logistic_regression.pdf", "course": "cs3481"}, ["substantial_omissions"], True, True),
        ("en", "doc-omissions2", "A fragment where two chapters are missing.", {"source": "chp5.pdf", "course": "cs3481"}, ["substantial_omissions"], True, True),
        ("en", "doc-unusable1", "unstructured noise with no heading or body.", {"source": "x.pdf", "course": "unknown"}, ["missing_essential_structure"], False, True),
        ("en", "doc-unusable2", "binary noise without any structure.", {"source": "y.pdf", "course": "unknown"}, ["missing_essential_structure"], False, True),
        ("zh", "doc-good-zh1", "完整小节，含标题、正文和页码定位。", {"source": "勾股定理讲义.pdf", "course": "zh-course"}, [], True, True),
        ("zh", "doc-good-zh2", "完整章节，含标题、正文和编号。", {"source": "一元二次方程讲义.pdf", "course": "zh-course"}, [], True, True),
        ("zh", "doc-minor-zh1", "含标题和正文的小节。", {"source": "一元二次方程讲义.pdf", "course": "zh-course"}, ["minor_parse_limitation"], True, True),
        ("zh", "doc-missing-source-zh", "结构完整但缺少来源信息的片段。", {"source": "", "course": "unknown"}, [], True, False),
        ("zh", "doc-omissions-zh", "缺少重要章节的片段。", {"source": "牛顿第二定律讲义.pdf", "course": "zh-course"}, ["substantial_omissions"], True, True),
        ("zh", "doc-unusable-zh", "无标题无正文的乱码内容。", {"source": "z.pdf", "course": "unknown"}, ["missing_essential_structure"], False, True),
        ("en", "doc-good3", "A complete module with title, sections and a source locator.", {"source": "Association Analysis.pdf", "course": "cs3481"}, [], True, True),
        ("en", "doc-minor3", "A section with title and body, a minor table parse issue.", {"source": "Naive Bayes Classification with Python and Scikit-Learn.ipynb", "course": "cs3481"}, ["minor_parse_limitation"], True, True),
        ("en", "doc-omissions3", "A fragment missing its worked examples.", {"source": "Association Analysis (Itemset Representation).pdf", "course": "cs3481"}, ["substantial_omissions"], True, True),
        ("en", "doc-unusable3", "raw binary with no text structure.", {"source": "adult.data", "course": "cs3481"}, ["missing_essential_structure"], False, True),
        ("zh", "doc-good3-zh", "完整章节，含标题、正文和来源定位。", {"source": "牛顿第二定律讲义.pdf", "course": "zh-course"}, [], True, True),
        ("zh", "doc-minor3-zh", "含标题和正文，有轻微表格解析问题。", {"source": "条件概率讲义.pdf", "course": "zh-course"}, ["minor_parse_limitation"], True, True),
        ("zh", "doc-omissions3-zh", "缺少例题的片段。", {"source": "矩阵讲义.pdf", "course": "zh-course"}, ["substantial_omissions"], True, True),
        ("zh", "doc-unusable3-zh", "无文本结构的原始数据。", {"source": "raw.data", "course": "unknown"}, ["missing_essential_structure"], False, True),
    ]
    for language, doc, fragment, meta, flags, has_structure, has_source in cases:
        score = _corpus_quality_score(flags, has_structure, has_source)
        samples.append(
            _judgment(
                sample_id=_sid(samples), definition_id="corpus.quality.v1", language=language,
                document_id="doc-corpus-quality", node_id=doc, question_family="corpus_quality",
                label_tier=LABEL_TIER_OBJECTIVE,
                label_evidence=f"code-verified: corpus_quality rule -> {score} (flags={flags}, structure={has_structure}, source={has_source})",
                state={"document_fragment": fragment, "source_metadata": meta, "parse_flags": flags},
                question=_score("corpus.quality.v1", criteria),
                label={"score_index": score},
            )
        )
    return samples


def _build_trajectory(samples):
    criteria = _questions_by_key()["intent.next_action.v1"]["criteria"]
    cases = [
        ("en", "doc-trajectory", "node-t1", "teach", None,
         [("what is eps?", "ANSWER_ONLY"), ("thanks", "CONTINUE")], "CONTINUE", "continue"),
        ("en", "doc-trajectory", "node-t2", "teach", None,
         [("explain the detour", "ANSWER_AND_RESUME"), ("now resume", "CONTINUE")], "CONTINUE", "resume"),
        ("en", "doc-trajectory", "node-t3", "teach", None,
         [("I need a break", "PAUSE")], "PAUSE", "pause"),
        ("en", "doc-trajectory", "node-t4", "assess", "A1",
         [("let me review", "CONTINUE"), ("submit", "SUBMIT_ASSESSMENT")], "SUBMIT_ASSESSMENT", "submit the assessment"),
        ("en", "doc-trajectory", "node-t5", "teach", None,
         [("do a practice problem", "QUIZ_WAIT")], "QUIZ_WAIT", "give me a question"),
        ("en", "doc-trajectory", "node-t11", "teach", None,
         [("explain eps", "ANSWER_ONLY"), ("back to the main line", "CONTINUE")], "CONTINUE", "back to the main line"),
        ("zh", "doc-trajectory", "node-t6", "teach", None,
         [("eps 是什么？", "ANSWER_ONLY"), ("谢谢", "CONTINUE")], "CONTINUE", "继续"),
        ("zh", "doc-trajectory", "node-t7", "teach", None,
         [("讲一下这个岔路", "ANSWER_AND_RESUME"), ("回到主线", "CONTINUE")], "CONTINUE", "回到主线"),
        ("zh", "doc-trajectory", "node-t8", "teach", None,
         [("我需要休息", "PAUSE")], "PAUSE", "暂停"),
        ("zh", "doc-trajectory", "node-t9", "assess", "A1",
         [("我再看看", "CONTINUE"), ("交卷", "SUBMIT_ASSESSMENT")], "SUBMIT_ASSESSMENT", "交卷"),
        ("zh", "doc-trajectory", "node-t10", "teach", None,
         [("来一题", "QUIZ_WAIT")], "QUIZ_WAIT", "做一题"),
        ("zh", "doc-trajectory", "node-t12", "teach", None,
         [("解释一下判别式", "ANSWER_ONLY"), ("答完再继续", "ANSWER_AND_RESUME")], "ANSWER_AND_RESUME", "答完再继续"),
    ]
    for language, doc, node, mode, assessment, turns, final_action, final_message in cases:
        state = {
            "conversation": [{"role": "user", "content": m} for m, _ in turns],
            "fixed_anchor": {"node_id": node},
            "current_mode": mode,
            "active_assessment": assessment,
            "message": final_message,
        }
        explicit = _explicit_for(final_message, mode, assessment)
        tier = LABEL_TIER_OBJECTIVE if explicit == final_action else LABEL_TIER_SILVER
        evidence = (
            f"code-verified: route_explicit_command({final_message!r}) -> {final_action}"
            if tier == LABEL_TIER_OBJECTIVE
            else f"DeepSeek suggestion, unreviewed: trajectory -> {final_action}"
        )
        samples.append(
            _judgment(
                sample_id=_sid(samples), definition_id="intent.next_action.v1", language=language,
                document_id=doc, node_id=node, question_family="trajectory", label_tier=tier,
                label_evidence=evidence, state=state,
                question=_choice("intent.next_action.v1", criteria),
                label={"choice": final_action},
            )
        )
    return samples


def _explicit_for(message, mode, assessment):
    from app.learning.intent_commands import route_explicit_command

    return route_explicit_command(message, current_mode=mode, active_assessment=assessment)


def _build_image(samples):
    cases = [
        ("en", "What is the Red value of color index 1 in the 16-color table?",
         "The GE2324 Assignment 2 transcription lists index 1 as (8, 52, 73).", "8"),
        ("en", "How many distinct RGB colors does the image initially contain?",
         "The GE2324 Assignment 2 transcription states the image initially contains 16 different colors.", "16"),
        ("en", "Which clustering method is used to reduce the colors from 16 to 3?",
         "The transcription asks to use K-means clustering to reduce the number of colors.", "K-means"),
        ("en", "Which distance is used when clustering the colors?",
         "The transcription specifies Euclidean distance for distances between colors and centroids.", "Euclidean"),
        ("zh", "图像最初包含多少种颜色？",
         "GE2324 Assignment 2 转录说明图像最初包含 16 种不同颜色。", "16"),
        ("zh", "用什么方法把颜色从 16 种减少到 3 种？",
         "转录要求使用 K 均值聚类把颜色数量减少。", "K 均值"),
        ("zh", "颜色 1 的红色分量是多少？",
         "GE2324 Assignment 2 转录中颜色 1 为 (8, 52, 73)。", "8"),
        ("zh", "计算颜色间距离使用什么距离？",
         "转录规定使用欧氏距离计算颜色与质心之间的距离。", "欧氏距离"),
    ]
    for language, prompt, transcription, answer in cases:
        samples.append(
            _judgment(
                sample_id=_sid(samples), definition_id="image_transcription.v1", language=language,
                document_id="doc-image-transcription", node_id="node-ge2324-assignment2",
                question_family="image", label_tier=LABEL_TIER_SOURCE,
                label_evidence=(
                    "SOURCE_REVIEWED: answer taken verbatim from the in-repo transcription "
                    "data/transcriptions/*.md (GE2324 Assignment 2)."
                ),
                state={"prompt": prompt, "transcription": transcription},
                question={"type": "image", "instructions": prompt, "criteria": {}},
                label={"answer": answer},
            )
        )
    return samples


def _build_locator(samples):
    """locator family: exact-target protection (the exact locator keeps slot 0)."""
    score_criteria = _questions_by_key()["retrieval.support.v1"]["criteria"]
    cases = [
        ("en", "doc-locator", "node-loc-1", "lecture3.pdf page 2 question 1",
         [("node-loc-1-exact", "The answer to question 1 is in this chunk.", 4, True),
          ("node-loc-1-decoy", "Unrelated background material.", 0, False)]),
        ("en", "doc-locator", "node-loc-2", "notes.docx page 4",
         [("node-loc-2-decoy", "Unrelated note.", 0, False),
          ("node-loc-2-exact", "The requested page-4 content.", 4, True)]),
        ("zh", "doc-locator", "node-loc-3", "讲义.pdf 第 2 页 第 1 题",
         [("node-loc-3-exact", "第 1 题的答案在此片段中。", 4, True),
          ("node-loc-3-decoy", "无关的背景材料。", 0, False)]),
        ("zh", "doc-locator", "node-loc-4", "笔记.docx 第 4 页",
         [("node-loc-4-decoy", "无关笔记。", 0, False),
          ("node-loc-4-exact", "请求的第 4 页内容。", 4, True)]),
    ]
    for language, doc, node, query, candidates in cases:
        for cid, text, score, is_exact in candidates:
            label = {"score_index": score}
            if is_exact:
                label["expected_slot"] = 0
            samples.append(
                _judgment(
                    sample_id=_sid(samples), definition_id="retrieval.support.v1", language=language,
                    document_id=doc, node_id=node, question_family="locator",
                    label_tier=LABEL_TIER_OBJECTIVE,
                    label_evidence=(
                        "code-verified: exact-locator hit (the candidate matching the "
                        f"requested locator keeps slot 0) -> score {score}"
                    ),
                    state={"query": query, "exact_target": cid if is_exact else None, "top_k": 2,
                           "candidate_id": cid, "candidate_text": text,
                           "source_metadata": {"course": doc, "locator": query}},
                    question=_score("retrieval.support.v1", score_criteria),
                    label=label,
                )
            )
    return samples


def _build_disputed(samples):
    criteria = _questions_by_key()["intent.next_action.v1"]["criteria"]
    disputed = [
        ("en", "doc-disputed", "node-d1", "citation",
         "Does 'the model may converge to a local optimum' support the claim 'K-means always finds the global optimum'?",
         "The source span says K-means may converge to a local optimum.", False),
        ("zh", "doc-disputed", "node-d2", "citation",
         "来源“判别式大于零时有两个不相等实根”是否支持“方程有两个根”这一笼统说法？",
         "来源明确两个不相等实根，但“两个根”的笼统说法是否成立取决于读法。", True),
    ]
    for language, doc, node, family, claim, span, reading_a in disputed:
        samples.append(
            _judgment(
                sample_id=_sid(samples), definition_id="source.supports_claim.v1", language=language,
                document_id=doc, node_id=node, question_family=family,
                label_tier=LABEL_TIER_DISPUTED,
                label_evidence=(
                    "DISPUTED. Reading A: supported (the span substantively supports the "
                    "claim). Reading B: not supported (the span is weaker/narrower than the "
                    "claim). Both readings recorded; excluded from single-label metrics."
                ),
                state={"claim": claim, "source_span": span, "source_version": "v1", "task_scope": doc},
                question=_noul(NOUL_INSTRUCTIONS),
                label={"noul": reading_a},
            )
        )
    # an intent dispute
    samples.append(
        _judgment(
            sample_id=_sid(samples), definition_id="intent.next_action.v1", language="zh",
            document_id="doc-disputed", node_id="node-d3", question_family="intent",
            label_tier=LABEL_TIER_DISPUTED,
            label_evidence=(
                "DISPUTED. Reading A: ANSWER_AND_RESUME (answer the sub-question then return). "
                "Reading B: ANSWER_ONLY (answer only, do not advance). Both readings recorded."
            ),
            state={"message": "先回答这个问题再说", "fixed_anchor": {"node_id": "node-d3"},
                   "current_mode": "teach", "active_assessment": None},
            question=_choice("intent.next_action.v1", criteria),
            label={"choice": "ANSWER_AND_RESUME"},
        )
    )
    return samples


# ----------------------------------------------------------------------------- assemble


def _build_split_coverage_atoms(samples):
    """Content added so the two priority definitions can actually be fitted and evaluated.

    The split is assigned by ``sha256(document_id|node_id|question_family) % 5`` over
    ``(train, train, train, calibration, test)``. That rule is untouched here — what it did
    produce, by chance, was a dataset where two definitions the promotion work depends on
    had no usable slot:

    * ``retrieval.support.v1`` (the task's **first** promotion candidate): 10 groups landed
      6 train / 4 test / **0 calibration**, so no threshold could be fitted for it;
    * ``pedagogy.next_method.v1``: 11 groups landed 20 train / 4 calibration / **0 test**, so
      nothing was held out to evaluate it on.

    The keys below were chosen *by slot* on purpose — they are authored identifiers, and the
    labels still come from each family's own deterministic rule (`_retrieval_rule_score` for
    the retrieval atoms) or tiering, so nothing about the labels is selected. Without this,
    §14's first priority cannot be executed at all; with it, the family gains two calibration
    groups and one test group.

    Appended last on purpose: `_sid` numbers by position, so inserting these earlier would
    renumber every later sample and invalidate the ids quoted in the reports.
    """
    retrieval_atoms = [
        {
            "doc": "doc-cs3481-hypothesis", "node": "node-type-two-error", "language": "en",
            "query": "What is a Type II error in hypothesis testing?",
            "topic": ["type ii", "error", "hypothesis"],
            "components": ["null hypothesis", "failing to reject"],
            "conditions": ["power", "beta"],
            "candidates": [
                "Gradient descent updates parameters along the negative gradient.",
                "This section discusses hypothesis testing error.",
                "Failing to reject the null hypothesis happens when the evidence is weak.",
                "Failing to reject a claim that is actually false lowers the power of a study.",
                (
                    "A type ii error is failing to reject the null hypothesis, and it "
                    "reduces the power of a test."
                ),
            ],
        },
        {
            "doc": "doc-cs3481-hypothesis", "node": "node-power", "language": "en",
            "query": "How is the power of a test defined?",
            "topic": ["power", "hypothesis", "test"],
            "components": ["reject", "alternative"],
            "conditions": ["probability", "type ii"],
            "candidates": [
                "An operating system kernel schedules processes and manages memory.",
                "The power of a statistical test grows with the sample size.",
                "We reject the null only when the evidence is strong enough.",
                "We reject a claim that is actually false with a probability set by the effect size.",
                "Power is the probability that we reject the null when the alternative holds.",
            ],
        },
        {
            "doc": "doc-cs3481-trees", "node": "node-bst-search", "language": "en",
            "query": "How does the search operation of a binary search tree work?",
            "topic": ["search", "binary search tree", "bst"],
            "components": ["left subtree", "right subtree"],
            "conditions": ["smaller", "greater"],
            "candidates": [
                "K-means alternates assignment and centroid updates.",
                "The search operation of a binary search tree visits one node per level.",
                "Search descends into the left subtree when the stored key is small.",
                "A search that follows the smaller keys descends into the left subtree.",
                (
                    "Search compares the key with the node, taking the left subtree when "
                    "it is smaller and the right subtree when it is greater."
                ),
            ],
        },
        {
            "doc": "doc-cs3481-regression", "node": "node-residual-plot", "language": "en",
            "query": "What should a residual plot look like for a well-fitted regression?",
            "topic": ["residual", "plot", "regression"],
            "components": ["residuals", "pattern"],
            "conditions": ["random", "fitted"],
            "candidates": [
                "An operating system kernel schedules processes.",
                "A residual plot is a standard diagnostic for a regression.",
                "The residuals of the regression show a clear pattern.",
                "The residuals plotted against the fitted values are informative.",
                "Residuals against fitted values should show no pattern and look random.",
            ],
        },
        {
            "doc": "doc-cs3481-trees", "node": "node-successor", "language": "en",
            "query": "How is the in-order successor of a node found?",
            "topic": ["successor", "in-order", "tree"],
            "components": ["right subtree", "leftmost"],
            "conditions": ["ancestor", "parent"],
            "candidates": [
                "Newton's second law relates force and acceleration.",
                "The in-order successor of a node depends on the tree structure.",
                "The successor is the leftmost node of the right subtree.",
                (
                    "The successor is the leftmost node when the path turns, otherwise "
                    "it is the first ancestor above it."
                ),
                (
                    "The in-order successor is the leftmost node of the right subtree, "
                    "or the first ancestor above it."
                ),
            ],
        },
        {
            "doc": "doc-zh-clustering", "node": "node-dbscan-zh", "language": "zh",
            "query": "DBSCAN 如何判断噪声点？",
            "topic": ["dbscan", "噪声", "聚类"],
            "components": ["核心点", "邻域"],
            "conditions": ["不属于", "任何"],
            "candidates": [
                "牛顿第二定律说明力等于质量乘以加速度。",
                "DBSCAN 是一种基于密度的聚类方法。",
                "DBSCAN 用邻域半径和最小点数描述密度。",
                "不属于任何邻域的点在 DBSCAN 中被单独处理。",
                "DBSCAN 把不属于任何核心点邻域的点标记为噪声点。",
            ],
        },
    ]
    _append_retrieval_atoms(samples, retrieval_atoms)

    pedagogy_cases = [
        ("en", "node-elbow-method", "How do I choose k for K-means?", "DEFINITION", LABEL_TIER_SOURCE),
        (
            "en", "node-elbow-method", "Show me a worked example of the elbow method",
            "WORKED_EXAMPLE", LABEL_TIER_SOURCE,
        ),
        (
            "en", "node-variance-bias", "Explain the bias-variance tradeoff from scratch",
            "DEFINITION", LABEL_TIER_SOURCE,
        ),
        (
            "en", "node-variance-bias",
            "Give a counterexample where a simpler model generalises better",
            "COUNTEREXAMPLE", LABEL_TIER_SOURCE,
        ),
        ("zh", "node-inertia", "逐步演示惯性的计算过程", "TRACE", LABEL_TIER_SOURCE),
    ]
    _append_pedagogy_cases(samples, pedagogy_cases)
    return samples


def build_samples():
    samples: list[JevJudgment] = []
    _build_retrieval(samples)
    _build_locator(samples)
    _build_claim(samples)
    _build_span_selection(samples)
    _build_intent(samples)
    _build_context(samples)
    _build_pedagogy(samples)
    _build_coverage(samples)
    _build_criterion(samples)
    _build_classification(samples)
    _build_exercise(samples)
    _build_prerequisite(samples)
    _build_corpus_quality(samples)
    _build_trajectory(samples)
    _build_image(samples)
    _build_disputed(samples)
    _build_split_coverage_atoms(samples)
    return samples


def _dataset_payload(samples):
    return {
        "dataset_name": "jev-judgments",
        "dataset_version": DATASET_VERSION,
        "description": (
            "Auditable multilingual judgment dataset for the Jev decision "
            "workstream: ~300 samples across all 12 decision definitions plus multi-turn "
            "trajectories, image-transcription-linked items and cross-permission "
            "negatives. Labels carry a tier (OBJECTIVE_VERIFIED / SOURCE_REVIEWED / "
            "SILVER_DEEPSEEK / DISPUTED) and evidence. Splits are assigned by "
            "(document_id, node_id, question_family) group, never by row."
        ),
        "definition_catalog_ref": "services/rag-api/app/jev/decision_catalog.json",
        "definition_version": DEFINITION_VERSION,
        "label_tier_definitions": {
            "OBJECTIVE_VERIFIED": "Verified by code (rule / id / sum / arithmetic).",
            "SOURCE_REVIEWED": "Cites a course source with a locator and review reason.",
            "SILVER_DEEPSEEK": "Unreviewed DeepSeek suggestion; NOT human gold.",
            "DISPUTED": "Genuinely ambiguous; both readings recorded.",
        },
        "precision_note": (
            "The Jev SDK reports probabilities rounded to 4 decimal places at the service "
            "boundary; calibration must use the highest-precision values available."
        ),
        "grouping_keys": list(GROUPING_KEYS),
        "dataset_status": DATASET_STATUS_LABELLED,
        "samples": [sample.to_dict() for sample in samples],
    }


def _write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    # `newline="\n"` and not the default: `Path.write_text` translates every `\n` to `\r\n` on
    # Windows, so rebuilding the dataset rewrote all ~13,000 line endings of a file the
    # repository keeps in LF. That turned a 35-sample addition into a whole-file diff — the
    # content was right and the diff was unreadable, which is how a reviewer stops reading.
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
    )


def build() -> None:
    samples = build_samples()
    _write_json(DATASET_PATH, _dataset_payload(samples))
    _write_json(SPLIT_PATH, build_split_manifest(samples))
    print(f"Wrote {DATASET_PATH} ({len(samples)} samples)")
    print(f"Wrote {SPLIT_PATH}")


def _manifest_samples(payload):
    return [
        JevJudgment(
            sample_id=s["sample_id"], definition_id=s["definition_id"],
            definition_version=s["definition_version"], language=s["language"],
            option_count=s["option_count"], document_id=s["document_id"], node_id=s["node_id"],
            question_family=s["question_family"], label_tier=s["label_tier"],
            label_evidence=s["label_evidence"], state=s["state"], questions=s["questions"],
            label=s["label"], split="",
        )
        for s in payload["samples"]
    ]


def validate() -> int:
    payload = load_jev_dataset(DATASET_PATH)
    validate_jev_dataset(payload)
    manifest = json.loads(SPLIT_PATH.read_text(encoding="utf-8"))
    samples = _manifest_samples(payload)
    validate_split_leakage(samples, manifest)
    from app.evaluation.jev_semantic_ablation import build_split_manifest, content_hash

    if content_hash(samples) != manifest["content_hash"]:
        raise ValueError("dataset content_hash does not match the frozen split manifest.")
    rebuilt = build_split_manifest(samples)
    if rebuilt["splits"] != manifest["splits"]:
        raise ValueError("split assignment is not reproducible (manifest drift).")
    print("validation ok: schema, label-tier invariants, split-leakage, content hash")
    return 0


def stats() -> int:
    payload = load_jev_dataset(DATASET_PATH)
    manifest = json.loads(SPLIT_PATH.read_text(encoding="utf-8"))
    samples = payload["samples"]
    by_def = Counter(s["definition_id"] for s in samples)
    by_tier = Counter(s["label_tier"] for s in samples)
    by_lang = Counter(s["language"] for s in samples)
    by_opt = Counter(s["option_count"] for s in samples)
    by_family = Counter(s["question_family"] for s in samples)
    print(f"total samples: {len(samples)}")
    print(f"per definition ({len(by_def)}):")
    for key in sorted(by_def):
        print(f"  {key}: {by_def[key]}")
    print("per label tier:")
    for key in sorted(by_tier):
        print(f"  {key}: {by_tier[key]}")
    print("per language:")
    for key in sorted(by_lang):
        print(f"  {key}: {by_lang[key]}")
    print("option-count distribution:")
    for key in sorted(by_opt):
        print(f"  {key} options: {by_opt[key]}")
    print("per question family:")
    for key in sorted(by_family):
        print(f"  {key}: {by_family[key]}")
    print("split sizes:")
    for name in ("train", "calibration", "test"):
        split = manifest["splits"][name]
        print(f"  {name}: {split['count']}")
    print(f"content_hash: {manifest['content_hash']}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", action="store_true", help="write the dataset + split manifest")
    parser.add_argument("--validate", action="store_true", help="load and validate both files")
    parser.add_argument("--stats", action="store_true", help="print composition statistics")
    args = parser.parse_args()
    if args.build:
        build()
    if args.validate and validate() != 0:
        return 2
    if args.stats and stats() != 0:
        return 2
    if not (args.build or args.validate or args.stats):
        parser.print_help()
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
