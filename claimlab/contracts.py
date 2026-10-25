"""Typed data contracts shared by the pipeline, skills, API and agent.

The core uses dataclasses (no hidden global state) so every skill can be
tested and reused independently. JSON helpers deliberately keep the wire
shape stable for fixtures and the UI.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

SCHEMA_VERSION = 1
CST = timezone(timedelta(hours=8))

Anchor = Literal["strong", "weak", "none"]
TaskMode = Literal["verify_claim", "research_topic"]
Grade = Literal["A", "B", "C", "D", "E"]
Relation = Literal["support", "refute", "unrelated", "unknown"]
Verdict = Literal["established", "refuted", "conflict", "suspect", "insufficient"]
FailureType = Literal["not_exists", "not_indexed", "query_mismatch", "search_disabled"]
Precision = Literal["precise", "fuzzy"]

# SearchPro only accepts these Cnt values, and expects a string in the JSON body
# (an integer reports "InvalidParameter: illegal Cnt").
VALID_CNT = (10, 20, 30, 40, 50)


def normalize_cnt(value: Any) -> int:
    """Snap any count to the nearest SearchPro-accepted value."""
    try:
        n = int(value)
    except (TypeError, ValueError):
        n = 10
    return min(VALID_CNT, key=lambda c: abs(c - n))


def now_iso() -> str:
    return datetime.now(CST).isoformat(timespec="seconds")


def make_id(prefix: str, *parts: Any) -> str:
    raw = "|".join(str(p) for p in parts)
    return f"{prefix}-{hashlib.sha1(raw.encode('utf-8')).hexdigest()[:10]}"


def jsonable(value: Any) -> Any:
    if hasattr(value, "__dataclass_fields__"):
        return {k: jsonable(v) for k, v in asdict(value).items()}
    if isinstance(value, dict):
        return {k: jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    return value


def dumps(value: Any) -> str:
    return json.dumps(jsonable(value), ensure_ascii=False, indent=2)


@dataclass
class ResearchTask:
    text: str
    mode: TaskMode = "verify_claim"
    constraints: dict[str, Any] = field(default_factory=dict)
    task_id: str = ""
    fixture_id: str | None = None
    created_at: str = field(default_factory=now_iso)
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.task_id:
            self.task_id = make_id("task", self.text[:80], self.created_at)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ResearchTask":
        return cls(
            text=data.get("text", ""),
            mode=data.get("mode", "verify_claim"),
            constraints=data.get("constraints") or {},
            task_id=data.get("task_id", ""),
            fixture_id=data.get("fixture_id"),
            created_at=data.get("created_at", now_iso()),
        )


@dataclass
class SearchRequest:
    query: str
    mode: int = 0
    site: str | None = None
    cnt: int = 10
    industry: str | None = None
    freshness: str | None = None
    schema_version: int = SCHEMA_VERSION

    def to_api_body(self) -> dict[str, Any]:
        body: dict[str, Any] = {"Query": self.query, "Cnt": str(normalize_cnt(self.cnt)), "Mode": self.mode}
        if self.site:
            body["Site"] = self.site
        if self.industry:
            body["Industry"] = self.industry
        if self.freshness:
            body["Freshness"] = self.freshness
        return body

    def cache_key(self) -> str:
        payload = {
            "query": self.query,
            "mode": self.mode,
            "site": self.site,
            "cnt": self.cnt,
            "industry": self.industry,
            "freshness": self.freshness,
        }
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@dataclass
class SearchPage:
    title: str = ""
    url: str = ""
    domain: str = ""
    site: str = ""
    date: str | None = None
    age_days: int | None = None
    passage: str = ""
    content: str = ""
    score: float | None = None
    pics: list[dict[str, Any]] = field(default_factory=list)
    favicon: str = ""
    authority_level: int | None = None
    strength: str = "snippet"  # full-ish / snippet / title

    def text(self) -> str:
        return " ".join(part for part in (self.title, self.passage, self.content) if part)


@dataclass
class SearchBatch:
    provider: str = ""
    request_id: str = ""
    version: str = ""
    pages: list[SearchPage] = field(default_factory=list)
    raw: Any = None
    latency_ms: float = 0.0
    warnings: list[str] = field(default_factory=list)
    error: str | None = None
    error_kind: str = ""  # auth | rate_limit | transport | server | client | unknown
    cache_hit: bool = False
    query: str = ""
    request: SearchRequest | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


@dataclass
class Claim:
    claim_id: str
    type: Literal["fact", "emotion"]
    text: str
    field: str = "unknown"
    value: str | int | float | None = None
    source_sentence: str = ""
    falsifiable: bool = True
    importance: int = 0
    concern: str | None = None
    search_terms: list[str] = dataclasses.field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Claim":
        return cls(
            claim_id=data.get("claim_id") or make_id("claim", data.get("text", "")),
            type=data.get("type", "fact"),
            text=data.get("text", ""),
            field=data.get("field", "unknown"),
            value=data.get("value"),
            source_sentence=data.get("source_sentence", ""),
            falsifiable=bool(data.get("falsifiable", True)),
            importance=int(data.get("importance", 0)),
            concern=data.get("concern"),
            search_terms=[str(item).strip() for item in (data.get("search_terms") or []) if str(item).strip()],
        )


@dataclass
class ExtractionResult:
    facts: list[Claim] = field(default_factory=list)
    emotions: list[Claim] = field(default_factory=list)
    dropped: list[dict[str, Any]] = field(default_factory=list)
    subject: str | None = None
    method: str = "llm"
    input_kind: str = "declarative"
    reason: str = ""
    guidance: str = ""

    @property
    def profile(self) -> dict[str, Any]:
        fact_count = len(self.facts)
        emotion_count = len(self.emotions)
        if fact_count >= 2 and emotion_count >= 2:
            quadrant = "混合"
        elif fact_count >= 2:
            quadrant = "事实为主"
        elif emotion_count >= 2:
            quadrant = "情绪宣泄"
        else:
            quadrant = "信息稀薄"
        concerns = sorted({e.concern or e.field for e in self.emotions if e.concern or e.field})
        return {
            "facts": fact_count,
            "emotions": emotion_count,
            "quadrant": quadrant,
            "concerns": concerns,
        }


@dataclass
class Requirement:
    """A searchable unit produced by requirement decomposition (S1).

    Unlike a Claim, a Requirement is not necessarily a falsifiable assertion:
    it can be a source-authenticity check, a historical explanation, or a
    policy lookup. It is the direct input to query construction.
    """

    requirement_id: str
    text: str
    field: str = "unknown"
    focus: str | None = None
    time_window: str = "12m"
    source_preference: str | None = None
    rationale: str = ""
    importance: int = 0
    search_terms: list[str] = dataclasses.field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Requirement":
        text = str(data.get("text") or "").strip()
        return cls(
            requirement_id=data.get("requirement_id") or make_id("req", text),
            text=text,
            field=data.get("field", "unknown"),
            focus=str(data.get("focus") or "").strip() or None,
            time_window=str(data.get("time_window") or "12m"),
            source_preference=data.get("source_preference"),
            rationale=str(data.get("rationale") or ""),
            importance=int(data.get("importance", 0)),
            search_terms=[str(item).strip() for item in (data.get("search_terms") or []) if str(item).strip()],
        )


@dataclass
class RequirementPlan:
    requirements: list[Requirement] = field(default_factory=list)
    domain: str = ""
    method: str = "heuristic"
    notes: list[str] = field(default_factory=list)


@dataclass
class QueryPlan:
    plan_id: str
    claim_id: str
    query: str
    mode: int = 0
    site: str | None = None
    cnt: int = 10
    industry: str | None = None
    freshness: str | None = None
    precision: Precision = "fuzzy"
    round: int = 0
    strategy: str = ""
    requirement_id: str = ""

    def to_request(self) -> SearchRequest:
        return SearchRequest(
            query=self.query,
            mode=self.mode,
            site=self.site,
            cnt=self.cnt,
            industry=self.industry,
            freshness=self.freshness,
        )


@dataclass
class Evidence:
    evidence_id: str
    title: str = ""
    url: str = ""
    domain: str = ""
    site: str = ""
    date: str | None = None
    fetched_at: str = field(default_factory=now_iso)
    passage: str = ""
    content: str = ""
    score: float | None = None
    grade: Grade = "D"
    grade_reason: str = ""
    verifiable: str = "需人工"
    relation: Relation = "unrelated"
    quote: str = ""
    observed_value: str | None = None
    cluster_id: str = ""
    cluster_size: int = 1
    cluster_domains: list[str] = field(default_factory=list)
    retrieval_query: str = ""
    older: bool = False
    strength: str = "snippet"
    quote_rejected: bool = False

    @property
    def rank_key(self) -> tuple:
        order = {"A": 0, "B": 1, "C": 2, "D": 3, "E": 4}
        return (order.get(self.grade, 9), self.date or "", -(self.score or 0.0), self.url)


@dataclass
class Cluster:
    cluster_id: str
    member_ids: list[str] = field(default_factory=list)
    domains: list[str] = field(default_factory=list)
    size: int = 0
    representative_url: str = ""


@dataclass
class LayeredVerdict:
    all_evidence: Verdict = "insufficient"
    a_level_only: Verdict = "insufficient"


@dataclass
class ClusterVotes:
    support: int = 0
    refute: int = 0
    note: str = ""
    clusters: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class VerificationUnit:
    unit_id: str
    assertion: dict[str, Any]
    source_sentence: str = ""
    claim_id: str = ""
    evidence: list[Evidence] = field(default_factory=list)
    verdict: Verdict = "insufficient"
    rule_id: str = "R5"
    layered: LayeredVerdict = field(default_factory=LayeredVerdict)
    cluster_votes: ClusterVotes = field(default_factory=ClusterVotes)
    action: str = ""
    unverified: list[str] = field(default_factory=list)
    failure_type: FailureType | None = None
    calls_used: int = 0
    queries_used: int = 0
    concern: str | None = None
    advisory: dict[str, Any] | None = None


@dataclass
class QueryTrace:
    query_id: str
    query: str
    params: dict[str, Any] = field(default_factory=dict)
    calls: int = 0
    results: int = 0
    new_clusters: int = 0
    new_ab: int = 0
    status: str = "ok"
    error: str | None = None
    cache_hit: bool = False


@dataclass
class Round:
    round_id: str
    assertion_id: str
    type: str = "initial"  # initial | resupply | cross_check | extension
    intent: str = ""
    changed_strategy: str = ""
    queries: list[QueryTrace] = field(default_factory=list)
    new_clusters: int = 0
    new_ab: int = 0
    stop_reason: str = ""


@dataclass
class ReportStats:
    calls: int = 0
    cache_hits: int = 0
    results: int = 0
    unique_results: int = 0
    clusters: int = 0
    a_level: int = 0
    b_level: int = 0
    duration_ms: int = 0
    stop_reason: str = ""


@dataclass
class ResearchReport:
    task: ResearchTask
    profile: dict[str, Any] = field(default_factory=dict)
    units: list[VerificationUnit] = field(default_factory=list)
    rounds: list[Round] = field(default_factory=list)
    trace: list[dict[str, Any]] = field(default_factory=list)
    stats: ReportStats = field(default_factory=ReportStats)
    conflicts: list[dict[str, Any]] = field(default_factory=list)
    unverified: list[str] = field(default_factory=list)
    citations: list[str] = field(default_factory=list)
    aggregate: dict[str, Any] = field(default_factory=dict)
    degraded: dict[str, Any] = field(default_factory=dict)
    guidance: str = ""
    disclaimer: str = "本页只核对公开说法与来源，不评价个人，不构成消费建议。"
    kind: str = "verification"
    generated_at: str = field(default_factory=now_iso)
    schema_version: int = SCHEMA_VERSION
