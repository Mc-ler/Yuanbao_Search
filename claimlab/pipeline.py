"""Bounded verification pipeline.

This is the P0 execution mode: a fixed sequence over the same skills the
future Research Agent will call as tools. Every loop has a hard budget and a
progress check; the judge is deterministic and never delegated to the LLM.
"""

from __future__ import annotations

import inspect
import time
from typing import Any, Awaitable, Callable

from .config import Settings
from .contracts import (
    Claim,
    ClusterVotes,
    Evidence,
    ExtractionResult,
    LayeredVerdict,
    QueryTrace,
    ReportStats,
    ResearchReport,
    ResearchTask,
    Round,
    VerificationUnit,
    make_id,
    now_iso,
)
from .search.archive import ArchiveWriter
from .search.budget import Budget
from .search.gateway import SearchGateway
from .search.normalize import strip_html
from .skills import dedup as dedup_skill
from .skills import extraction as extraction_skill
from .skills import grading, judging, matching, query as query_skill, reporting, safety

EventCallback = Callable[[dict[str, Any]], Awaitable[None] | None]


class Pipeline:
    def __init__(
        self,
        settings: Settings,
        gateway: SearchGateway,
        llm: Any,
        archive: ArchiveWriter,
        budget: Budget,
        on_event: EventCallback | None = None,
    ) -> None:
        self.settings = settings
        self.gateway = gateway
        self.llm = llm
        self.archive = archive
        self.budget = budget
        self.on_event = on_event
        self.run_id = ""
        self.trace: list[dict[str, Any]] = []
        self.rounds: list[Round] = []
        self.units: list[Any] = []
        self.total_results = 0

    async def _emit(self, event_type: str, payload: dict[str, Any]) -> None:
        event = {
            "seq": len(self.trace) + 1,
            "ts": now_iso(),
            "run_id": self.run_id,
            "type": event_type,
            **payload,
        }
        self.trace.append(event)
        try:
            self.archive.write_event(self.run_id, event_type, payload)
        except Exception:
            pass
        if self.on_event is None:
            return
        try:
            result = self.on_event(event)
            if inspect.isawaitable(result):
                await result
        except Exception:
            pass

    def _context(self, claim: Claim, unique_pages: list, queries: set, calls: int) -> dict[str, Any]:
        return {
            "pages_count": len(unique_pages),
            "queries_count": len(queries),
            "pages_text": " ".join(page.text() for page in unique_pages),
            "calls_used": calls,
        }

    def _build_evidence(
        self,
        claim: Claim,
        unique_pages: list,
        matches: list[matching.MatchResult],
        dedup_result: dedup_skill.DedupResult,
        page_grades: dict[str, grading.GradeResult],
        page_queries: dict[str, str],
    ) -> list[Evidence]:
        clusters = {cluster.cluster_id: cluster for cluster in dedup_result.clusters}
        result: list[Evidence] = []
        for index, page in enumerate(unique_pages):
            key = dedup_skill.page_key(page, index)
            grade = page_grades.get(key)
            if grade is None:
                grade = grading.grade_page(page)
            cluster_id = dedup_result.page_cluster.get(key, "")
            cluster = clusters.get(cluster_id)
            match = matches[index] if index < len(matches) else matching.MatchResult(index, "unrelated")
            result.append(
                Evidence(
                    evidence_id=make_id("ev", claim.claim_id, page.url or page.title, index),
                    title=page.title,
                    url=page.url,
                    domain=page.domain,
                    site=page.site,
                    date=page.date,
                    passage=page.passage,
                    content=page.content,
                    score=page.score,
                    grade=grade.grade,
                    grade_reason=grade.reason,
                    verifiable=grade.verifiable,
                    relation=match.relation,  # type: ignore[arg-type]
                    quote=strip_html(match.quote),
                    observed_value=match.observed_value,
                    cluster_id=cluster_id,
                    cluster_size=cluster.size if cluster else 1,
                    cluster_domains=list(cluster.domains) if cluster else ([page.domain] if page.domain else []),
                    retrieval_query=page_queries.get(key, ""),
                    older=grade.older,
                    strength=page.strength,
                    quote_rejected=match.quote_rejected,
                )
            )
        return result

    async def run(
        self,
        task: ResearchTask,
        cancel_event: Any | None = None,
        on_event: EventCallback | None = None,
        run_id: str | None = None,
        search_off: bool = False,
    ) -> ResearchReport:
        if on_event is not None:
            self.on_event = on_event
        if task.mode != "verify_claim":
            raise ValueError("research_topic 将在 P2 的 Research Agent 中启用；当前仅支持 verify_claim")
        self.run_id = run_id or make_id("run", task.task_id, now_iso())
        started = time.monotonic()
        safety.check_task(task)
        await self._emit(
            "run.started",
            {
                "task_id": task.task_id,
                "mode": task.mode,
                "subject": task.subject,
                "city": task.city,
                "text": task.text,
                "demo": self.settings.demo_mode,
                "offline": self.settings.offline,
                "search_off": search_off,
            },
        )

        extraction: ExtractionResult = await extraction_skill.extract_claims(self.llm, task)
        subject = task.subject or extraction.subject
        await self._emit(
            "split.done",
            {
                "subject": subject,
                "facts": [
                    {
                        "claim_id": claim.claim_id,
                        "text": claim.text,
                        "field": claim.field,
                        "value": claim.value,
                        "source_sentence": claim.source_sentence,
                    }
                    for claim in extraction.facts
                ],
                "emotions": [
                    {"text": claim.text, "field": claim.field, "concern": claim.concern}
                    for claim in extraction.emotions
                ],
                "dropped": extraction.dropped,
                "profile": extraction.profile,
                "method": extraction.method,
            },
        )

        if not extraction.facts:
            report = reporting.build_report(
                task,
                extraction,
                [],
                [],
                self.trace,
                ReportStats(stop_reason="no_falsifiable_claim", duration_ms=int((time.monotonic() - started) * 1000)),
            )
            safety.lint_report_text(report)
            await self._emit("run.done", {"report": reporting.report_to_dict(report), "stop_reason": "no_falsifiable_claim"})
            return report

        if search_off:
            for claim in extraction.facts[:3]:
                unit = VerificationUnit(
                    unit_id=make_id("unit", claim.claim_id, claim.text),
                    assertion={"field": claim.field, "value": claim.value, "text": claim.text},
                    source_sentence=claim.source_sentence,
                    claim_id=claim.claim_id,
                    evidence=[],
                    verdict="insufficient",
                    rule_id="R5",
                    layered=LayeredVerdict(all_evidence="insufficient", a_level_only="insufficient"),
                    cluster_votes=ClusterVotes(),
                    action="搜索已关闭：无法判读任何断言",
                    unverified=[claim.concern or claim.field],
                    failure_type="search_disabled",
                    calls_used=0,
                    concern=claim.concern,
                )
                self.units.append(unit)
                await self._emit(
                    "unit.verdict",
                    {
                        "unit_id": unit.unit_id,
                        "claim_id": claim.claim_id,
                        "assertion": unit.assertion,
                        "verdict": unit.verdict,
                        "rule_id": unit.rule_id,
                        "layered": {"all_evidence": unit.verdict, "a_level_only": unit.verdict},
                        "cluster_votes": {"support": 0, "refute": 0, "note": ""},
                        "action": unit.action,
                        "failure_type": unit.failure_type,
                        "calls_used": 0,
                        "queries_used": 0,
                        "evidence": [],
                    },
                )
            stats = ReportStats(
                calls=0,
                cache_hits=0,
                results=0,
                unique_results=0,
                clusters=0,
                duration_ms=int((time.monotonic() - started) * 1000),
                stop_reason="search_off",
            )
            report = reporting.build_report(task, extraction, self.units, [], self.trace, stats)
            safety.lint_report_text(report)
            await self._emit("run.stats", {"calls": 0, "cache_hits": 0, "results": 0, "clusters": 0, "stop_reason": "search_off"})
            await self._emit("run.done", {"report": reporting.report_to_dict(report), "stop_reason": "search_off"})
            return report

        for claim in extraction.facts[:3]:
            if cancel_event is not None and getattr(cancel_event, "is_set", lambda: False)():
                self.budget.stop_reason = "cancelled"
                break
            await self._emit(
                "claim.started",
                {"claim_id": claim.claim_id, "text": claim.text, "field": claim.field},
            )
            pool_pages: list = []
            page_grades: dict[str, grading.GradeResult] = {}
            page_queries: dict[str, str] = {}
            used_plan_keys: set[tuple[str, str | None, str | None]] = set()
            verdict = "insufficient"
            dedup_result = dedup_skill.DedupResult([], [], {})
            matches: list[matching.MatchResult] = []
            evidence: list[Evidence] = []
            unique_pages: list = []
            prev_clusters = 0
            prev_ab = 0

            for round_no in (0, 1):
                if cancel_event is not None and getattr(cancel_event, "is_set", lambda: False)():
                    self.budget.stop_reason = "cancelled"
                    break
                if round_no == 1:
                    if verdict not in {"conflict", "insufficient", "suspect"}:
                        break
                    if not self.budget.can_call(claim.claim_id):
                        break
                plans = query_skill.plan_queries(
                    claim,
                    subject=subject,
                    city=task.city,
                    round_no=round_no,
                    used=used_plan_keys,
                )
                if not plans:
                    break
                round_type = "initial" if round_no == 0 else "resupply"
                round_intent = "首轮检索" if round_no == 0 else "换策略补搜"
                round_obj = Round(
                    round_id=make_id("round", claim.claim_id, round_no),
                    assertion_id=claim.claim_id,
                    type=round_type,
                    intent=round_intent,
                )
                await self._emit(
                    "round.started",
                    {"claim_id": claim.claim_id, "round": round_no, "round_type": round_type, "intent": round_intent},
                )
                for plan in plans:
                    if not self.budget.can_call(claim.claim_id):
                        round_obj.stop_reason = "budget"
                        break
                    await self._emit(
                        "query.planned",
                        {
                            "claim_id": claim.claim_id,
                            "round": round_no,
                            "query_id": plan.plan_id,
                            "query": plan.query,
                            "params": {
                                "mode": plan.mode,
                                "site": plan.site,
                                "industry": plan.industry,
                                "freshness": plan.freshness,
                                "cnt": plan.cnt,
                            },
                            "precision": plan.precision,
                            "strategy": plan.strategy,
                        },
                    )
                    await self._emit("search.started", {"claim_id": claim.claim_id, "query_id": plan.plan_id, "query": plan.query})
                    batch = await self.gateway.search(self.run_id, claim.claim_id, plan)
                    query_trace = QueryTrace(
                        query_id=plan.plan_id,
                        query=plan.query,
                        params={
                            "mode": plan.mode,
                            "site": plan.site,
                            "industry": plan.industry,
                            "freshness": plan.freshness,
                            "cnt": plan.cnt,
                        },
                        calls=0 if batch.cache_hit else 1,
                        results=len(batch.pages),
                        status="error" if batch.error else "ok",
                        error=batch.error,
                        cache_hit=batch.cache_hit,
                    )
                    round_obj.queries.append(query_trace)
                    await self._emit(
                        "search.result",
                        {
                            "claim_id": claim.claim_id,
                            "query_id": plan.plan_id,
                            "query": plan.query,
                            "provider": batch.provider,
                            "cache_hit": batch.cache_hit,
                            "pages": len(batch.pages),
                            "warnings": batch.warnings,
                            "error": batch.error,
                            "error_kind": batch.error_kind,
                            "latency_ms": round(batch.latency_ms, 1),
                        },
                    )
                    if batch.error:
                        if batch.error_kind in {"budget", "auth", "config", "cache"}:
                            round_obj.stop_reason = batch.error_kind
                            break
                        continue
                    for page in batch.pages:
                        key = dedup_skill.page_key(page, len(pool_pages))
                        grade = grading.grade_page(page, plan.industry)
                        current = page_grades.get(key)
                        if current is None or grading.grade_rank(grade.grade) < grading.grade_rank(current.grade):
                            page_grades[key] = grade
                        page_queries.setdefault(key, plan.query)
                        pool_pages.append(page)
                        self.total_results += 1
                    used_plan_keys.add(query_skill.plan_key(plan))
                    if round_obj.stop_reason in {"budget", "auth", "config", "cache"}:
                        break

                dedup_result = dedup_skill.cluster_pages(pool_pages, self.settings.dedup_threshold)
                unique_pages = dedup_result.unique_pages
                matches = await matching.match_evidence(self.llm, claim, unique_pages)
                evidence = self._build_evidence(
                    claim, unique_pages, matches, dedup_result, page_grades, page_queries
                )
                unit_calls = self.budget.per_assertion.get(claim.claim_id, 0)
                context = self._context(claim, unique_pages, used_plan_keys, unit_calls)
                interim = judging.judge_unit(claim, evidence, context)
                verdict = interim.verdict
                ab_count = sum(
                    1 for item in evidence if item.grade in {"A", "B"} and item.relation in {"support", "refute"}
                )
                round_obj.new_clusters = max(0, len(dedup_result.clusters) - prev_clusters)
                round_obj.new_ab = max(0, ab_count - prev_ab)
                prev_clusters = len(dedup_result.clusters)
                prev_ab = ab_count
                if not round_obj.stop_reason:
                    if verdict in {"established", "refuted"}:
                        round_obj.stop_reason = "enough_evidence"
                    elif round_obj.new_clusters == 0 and round_obj.new_ab == 0:
                        round_obj.stop_reason = "no_progress"
                    elif not self.budget.can_call(claim.claim_id):
                        round_obj.stop_reason = "budget"
                    else:
                        round_obj.stop_reason = "continue"
                self.rounds.append(round_obj)
                await self._emit(
                    "round.judged",
                    {
                        "claim_id": claim.claim_id,
                        "round": round_no,
                        "verdict": interim.verdict,
                        "rule_id": interim.rule_id,
                        "new_clusters": round_obj.new_clusters,
                        "new_ab": round_obj.new_ab,
                        "stop_reason": round_obj.stop_reason,
                    },
                )
                if round_obj.stop_reason != "continue":
                    break

            if not evidence:
                interim = judging.judge_unit(
                    claim,
                    [],
                    {
                        "pages_count": 0,
                        "queries_count": len(used_plan_keys),
                        "pages_text": "",
                        "calls_used": self.budget.per_assertion.get(claim.claim_id, 0),
                    },
                )
            else:
                interim = judging.judge_unit(
                    claim,
                    evidence,
                    self._context(
                        claim,
                        unique_pages,
                        used_plan_keys,
                        self.budget.per_assertion.get(claim.claim_id, 0),
                    ),
                )
            interim.calls_used = self.budget.per_assertion.get(claim.claim_id, 0)
            self.units.append(interim)
            await self._emit(
                "unit.verdict",
                {
                    "unit_id": interim.unit_id,
                    "claim_id": claim.claim_id,
                    "assertion": interim.assertion,
                    "verdict": interim.verdict,
                    "rule_id": interim.rule_id,
                    "layered": {
                        "all_evidence": interim.layered.all_evidence,
                        "a_level_only": interim.layered.a_level_only,
                    },
                    "cluster_votes": {
                        "support": interim.cluster_votes.support,
                        "refute": interim.cluster_votes.refute,
                        "note": interim.cluster_votes.note,
                    },
                    "action": interim.action,
                    "failure_type": interim.failure_type,
                    "calls_used": interim.calls_used,
                    "queries_used": interim.queries_used,
                    "evidence": [
                        {
                            "evidence_id": item.evidence_id,
                            "title": item.title,
                            "url": item.url,
                            "site": item.site,
                            "domain": item.domain,
                            "date": item.date,
                            "grade": item.grade,
                            "verifiable": item.verifiable,
                            "relation": item.relation,
                            "quote": item.quote,
                            "observed_value": item.observed_value,
                            "cluster_id": item.cluster_id,
                            "cluster_size": item.cluster_size,
                            "older": item.older,
                            "strength": item.strength,
                            "quote_rejected": item.quote_rejected,
                        }
                        for item in interim.evidence
                    ],
                },
            )

        a_level = sum(
            1 for unit in self.units for item in unit.evidence if item.grade == "A" and item.relation in {"support", "refute"}
        )
        b_level = sum(
            1 for unit in self.units for item in unit.evidence if item.grade == "B" and item.relation in {"support", "refute"}
        )
        unique_urls = {item.url for unit in self.units for item in unit.evidence if item.url}
        cluster_ids = {item.cluster_id for unit in self.units for item in unit.evidence if item.cluster_id}
        stats = ReportStats(
            calls=self.gateway.calls,
            cache_hits=self.gateway.cache_hits,
            results=self.total_results,
            unique_results=len(unique_urls),
            clusters=len(cluster_ids),
            a_level=a_level,
            b_level=b_level,
            duration_ms=int((time.monotonic() - started) * 1000),
            stop_reason=self.budget.stop_reason or "completed",
        )
        report = reporting.build_report(task, extraction, self.units, self.rounds, self.trace, stats)
        safety.lint_report_text(report)
        await self._emit(
            "run.stats",
            {
                "calls": stats.calls,
                "cache_hits": stats.cache_hits,
                "results": stats.results,
                "unique_results": stats.unique_results,
                "clusters": stats.clusters,
                "a_level": stats.a_level,
                "b_level": stats.b_level,
                "duration_ms": stats.duration_ms,
                "stop_reason": stats.stop_reason,
                "budget": self.budget.summary(),
            },
        )
        await self._emit(
            "run.done",
            {"report": reporting.report_to_dict(report), "stop_reason": stats.stop_reason},
        )
        return report
