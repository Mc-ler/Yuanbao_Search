"""Site-aware search wrapper.

SearchPro's ``Site`` filter is exact-host and fails closed: an apex host or
``gov.cn`` returns HTTP 200 with zero pages. Retrying once without ``Site``
keeps a bad LLM/template host from wasting a whole query slot.
"""

from __future__ import annotations

import logging
from dataclasses import replace
from typing import Any

from ..logging import event
from ..contracts import SearchBatch

logger = logging.getLogger("claimlab.search")


async def search_with_site_fallback(
    gateway: Any,
    run_id: str,
    assertion_id: str,
    plan: Any,
    *,
    use_cache: bool = True,
) -> SearchBatch:
    batch = await gateway.search(run_id, assertion_id, plan, use_cache=use_cache)
    site = getattr(plan, "site", None)
    if not site or not batch.ok or batch.pages:
        return batch
    try:
        retry_plan = replace(plan, site=None)
    except (TypeError, ValueError):
        return batch
    retry = await gateway.search(run_id, assertion_id, retry_plan, use_cache=use_cache)
    event(
        logger,
        "search.site_fallback",
        run_id=run_id,
        assertion_id=assertion_id,
        site=site,
        first_pages=len(batch.pages),
        retry_pages=len(retry.pages),
        retry_error=retry.error,
    )
    if retry.ok and retry.pages:
        return retry
    return batch
