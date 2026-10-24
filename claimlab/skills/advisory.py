"""Non-binding LLM advisory for R5 (insufficient) claims.

R1-R5 remains the verdict. The advisory only explains possible reasons and next
verification steps; it must never overwrite verdict or rule_id.
"""

from __future__ import annotations

from typing import Any

SYSTEM_PROMPT = """你是查证参考意见生成器。给定一个判定为“证据不足”的断言及其证据，给出非约束性的参考意见。只输出 JSON。
规则：
1. 这不是判定；禁止输出“成立/不成立/已证实/已辟谣”等结论词，也禁止改变 rule_id。
2. 只能依据给定证据；没有证据就写“不知道/没有结果/无法确定”，不要编造来源、数字或因果。
3. 只说明可观察到的原因（未被索引、查询不匹配、来源不足）和下一步核实路径；不要猜测未发生的事实，不要编造机构/数字。
4. 如果连可观察原因也没有，直接写“不知道/没有结果/无法确定”。
输出：{"items":[{"unit_id":"...","text":"...","confidence":"low|medium","caveats":"..."}]}
"""


async def build_advisories(llm: Any, units: list[Any], max_claims: int = 3) -> dict[str, dict[str, Any]]:
    targets = [unit for unit in units if getattr(unit, "verdict", "") == "insufficient"][:max_claims]
    if not targets or llm is None:
        return {}
    payload = {
        "claims": [
            {
                "unit_id": unit.unit_id,
                "assertion": unit.assertion,
                "failure_type": unit.failure_type,
                "action": unit.action,
                "evidence": [
                    {
                        "grade": item.grade,
                        "relation": item.relation,
                        "title": item.title,
                        "url": item.url,
                        "quote": item.quote,
                    }
                    for item in (unit.evidence or [])[:6]
                ],
            }
            for unit in targets
        ]
    }
    try:
        data = await llm.json("advisory", payload, SYSTEM_PROMPT)
    except Exception:
        return {}
    if not isinstance(data, dict):
        return {}
    result: dict[str, dict[str, Any]] = {}
    for item in data.get("items") or []:
        if not isinstance(item, dict):
            continue
        unit_id = str(item.get("unit_id") or "")
        text = str(item.get("text") or "").strip()
        if not unit_id or not text:
            continue
        result[unit_id] = {
            "text": text,
            "confidence": str(item.get("confidence") or "low"),
            "caveats": str(item.get("caveats") or ""),
        }
    return result
