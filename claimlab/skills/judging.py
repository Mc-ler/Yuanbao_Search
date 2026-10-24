"""Lexicographic verdicts R1-R5.

The judge is deliberately boring code. The model may read and write, but it
never decides the verdict; this is what makes the same fixture reproduce the
same answer and what lets the UI print the rule id that fired.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from typing import Any

from ..config import CONFIG_DIR
from ..contracts import (
    Claim,
    ClusterVotes,
    Evidence,
    LayeredVerdict,
    VerificationUnit,
    make_id,
)

FIELD_LABELS = {
    "business_status": "营业状态",
    "price": "价格口径",
    "hours": "营业时间",
    "penalty": "处罚记录",
    "license": "许可/资质",
    "address": "地址",
    "reservation": "预约/门票",
    "ad_disclosure": "广告标识",
    "unknown": "该说法",
}

FIELD_KEYWORDS = {
    "business_status": ["营业", "闭店", "停业"],
    "price": ["人均", "元", "价格"],
    "hours": ["营业", "周一", "时间"],
    "penalty": ["处罚", "罚款", "抽检"],
    "license": ["许可", "资质"],
    "address": ["地址", "路", "号"],
    "reservation": ["预约", "门票", "限流"],
    "ad_disclosure": ["广告", "探店", "推广"],
}


@lru_cache(maxsize=1)
def _lexicons() -> dict[str, Any]:
    return json.loads((CONFIG_DIR / "lexicons.json").read_text(encoding="utf-8"))


def specificity(text: str) -> tuple[int, list[str]]:
    config = _lexicons().get("specificity", {})
    matched: list[str] = []
    for category, patterns in config.items():
        if category == "entity":
            if any(word in text for word in patterns):
                matched.append(category)
            continue
        if any(re.search(pattern, text) for pattern in patterns):
            matched.append(category)
    return len(matched), matched


def specificity_level(count: int) -> str:
    if count <= 0:
        return "无"
    if count == 1:
        return "低"
    if count == 2:
        return "中"
    return "高"


def _numeric(value: Any) -> float | None:
    if value is None:
        return None
    match = re.search(r"-?\d+(?:\.\d+)?", str(value))
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def _conflicting_values(pool: list[Evidence]) -> list[str]:
    values: dict[str, set[str]] = {}
    for item in pool:
        if item.grade not in {"A", "B"} or item.relation != "support":
            continue
        number = _numeric(item.observed_value)
        if number is None:
            continue
        cluster = item.cluster_id or item.evidence_id
        values.setdefault(cluster, set()).add(f"{number:g}")
    distinct = sorted({value for cluster_values in values.values() for value in cluster_values})
    clusters_with_values = sum(1 for cluster_values in values.values() if cluster_values)
    if len(distinct) >= 2 and clusters_with_values >= 2:
        return distinct
    return []


def _verdict(pool: list[Evidence], only_a: bool = False, claim_text: str = "") -> tuple[str, str]:
    relevant = [item for item in pool if item.relation in {"support", "refute"}]
    if only_a:
        relevant = [item for item in relevant if item.grade == "A"]
    a_support = [item for item in relevant if item.grade == "A" and item.relation == "support"]
    a_refute = [item for item in relevant if item.grade == "A" and item.relation == "refute"]
    b_support = [item for item in relevant if item.grade in {"A", "B"} and item.relation == "support"]
    b_refute = [item for item in relevant if item.grade in {"A", "B"} and item.relation == "refute"]

    # R1: an A-level refutation wins unless an A-level source supports the claim.
    if a_refute and not a_support:
        return "refuted", "R1"
    # R2: A-level support with no A/B refutation.
    if a_support and not a_refute and not b_refute:
        return "established", "R2"
    # R2b: two independent B-or-better clusters supporting, no B+ refutation,
    # and the supports agree on the value (otherwise it is a conflict).
    support_clusters = {item.cluster_id or item.evidence_id for item in b_support}
    conflicting_values = _conflicting_values(relevant)
    if len(support_clusters) >= 2 and not b_refute and not conflicting_values:
        return "established", "R2b"
    # R3: contradiction, including conflicting values in the same field.
    if (a_support and a_refute) or (b_support and b_refute) or conflicting_values:
        return "conflict", "R3"
    # R4: the same vague passage repeated across domains, with no verifiable detail.
    largest_size = max((item.cluster_size for item in relevant), default=0)
    domain_count = len({domain for item in relevant for domain in (item.cluster_domains or [])})
    specificity_count, _ = specificity(claim_text)
    if largest_size >= 3 and domain_count >= 2 and specificity_count == 0:
        return "suspect", "R4"
    return "insufficient", "R5"


def _cluster_votes(pool: list[Evidence]) -> ClusterVotes:
    groups: dict[str, list[Evidence]] = {}
    for item in pool:
        if item.relation == "unrelated":
            continue
        key = item.cluster_id or item.evidence_id
        groups.setdefault(key, []).append(item)
    support = 0
    refute = 0
    clusters: list[dict[str, Any]] = []

    def rep_key(item: Evidence) -> tuple:
        order = {"A": 0, "B": 1, "C": 2, "D": 3, "E": 4}
        return (0 if item.relation in {"support", "refute"} else 1, order.get(item.grade, 9), item.date or "", item.url)

    for cluster_id, members in sorted(groups.items()):
        representative = sorted(members, key=rep_key)[0]
        if representative.relation == "support":
            support += 1
        elif representative.relation == "refute":
            refute += 1
        domains = sorted({domain for item in members for domain in (item.cluster_domains or [])})
        clusters.append(
            {
                "cluster_id": cluster_id,
                "size": max(item.cluster_size for item in members),
                "relation": representative.relation,
                "domains": domains,
                "representative": representative.url,
            }
        )
    notes = []
    for item in clusters:
        if item["size"] > 1:
            notes.append(f"{item['size']} 条结果同源，计 1 票")
    note = "；".join(dict.fromkeys(notes))
    return ClusterVotes(support=support, refute=refute, note=note, clusters=clusters)


def _failure(
    claim: Claim,
    pool: list[Evidence],
    context: dict[str, Any],
    verdict: str,
) -> tuple[str | None, str]:
    pages_count = int(context.get("pages_count") or 0)
    queries_count = int(context.get("queries_count") or 0)
    pages_text = str(context.get("pages_text") or "")
    if verdict != "insufficient":
        return None, ""
    if pages_count == 0:
        return "not_indexed", f"该信息可能未被公开索引；已尝试 {queries_count} 种检索路径，建议直接向商家确认"
    relevant = [item for item in pool if item.relation in {"support", "refute"}]
    if not relevant:
        keywords = FIELD_KEYWORDS.get(claim.field, [])
        related = any(keyword in pages_text for keyword in keywords)
        if related:
            return "not_exists", f"未找到支持该说法的可靠来源；检索到 {pages_count} 条相关内容均不涉及此点"
        return "query_mismatch", f"已尝试 {queries_count} 种检索路径，结果相关性不足"
    return "not_exists", f"已尝试 {queries_count} 种检索路径，未找到足以判定的来源"


def _format_value(value: Any) -> str:
    number = _numeric(value)
    if number is not None and float(number).is_integer():
        return str(int(number))
    return str(value)


def _action(claim: Claim, verdict: str, pool: list[Evidence], failure_text: str, cluster_votes: ClusterVotes) -> str:
    field = FIELD_LABELS.get(claim.field, "该说法")
    strongest = sorted([item for item in pool if item.relation in {"support", "refute"}], key=lambda item: item.rank_key)
    if verdict == "established":
        if claim.field == "price" and claim.value is not None:
            value = claim.value
            if isinstance(value, float) and value.is_integer():
                value = int(value)
            return f"证据支持；人均约 {value} 元，有 {max(1, cluster_votes.support)} 个独立来源簇佐证"
        return f"证据支持；{field}有 {max(1, cluster_votes.support)} 个独立来源簇佐证"
    if verdict == "refuted":
        quote = (strongest[0].quote if strongest else "")[:70]
        return f"建议谨慎；存在 A 级反驳{('：' + quote) if quote else ''}"
    if verdict == "conflict":
        values = sorted(
            {
                _format_value(item.observed_value)
                for item in pool
                if item.observed_value and item.relation in {"support", "refute"}
            },
            key=lambda value: (_numeric(value) is None, _numeric(value) or 0, value),
        )
        joined = " / ".join(values) if values else "多个口径"
        return f"口径不一致（{joined}）；建议按较高值准备，出发前再确认"
    if verdict == "suspect":
        return "多条内容同源且缺少可核验细节；建议谨慎，优先看官方来源"
    return f"无法判断；{failure_text}" if failure_text else "无法判断"


def judge_unit(claim: Claim, evidence: list[Evidence], context: dict[str, Any] | None = None) -> VerificationUnit:
    context = context or {}
    ordered = sorted(evidence, key=lambda item: item.rank_key) if evidence else []
    verdict, rule_id = _verdict(ordered, only_a=False, claim_text=claim.text)
    a_verdict, a_rule = _verdict(ordered, only_a=True, claim_text=claim.text)
    votes = _cluster_votes(ordered)
    failure_type, failure_text = _failure(claim, ordered, context, verdict)
    action = _action(claim, verdict, ordered, failure_text, votes)
    unverified: list[str] = []
    if verdict in {"insufficient", "suspect"}:
        unverified.append(claim.concern or FIELD_LABELS.get(claim.field, "该说法"))
    return VerificationUnit(
        unit_id=make_id("unit", claim.claim_id, claim.text),
        assertion={"field": claim.field, "value": claim.value, "text": claim.text},
        source_sentence=claim.source_sentence,
        claim_id=claim.claim_id,
        evidence=ordered,
        verdict=verdict,  # type: ignore[arg-type]
        rule_id=rule_id,
        layered=LayeredVerdict(all_evidence=verdict, a_level_only=a_verdict),  # type: ignore[arg-type]
        cluster_votes=votes,
        action=action,
        unverified=unverified,
        failure_type=failure_type,  # type: ignore[arg-type]
        calls_used=int(context.get("calls_used") or 0),
        queries_used=int(context.get("queries_count") or 0),
        concern=claim.concern,
    )
