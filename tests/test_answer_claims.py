from claimlab.skills.answer import _normalize_claims, build_citations


def rows():
    return [{
        "tier": "A/B",
        "top_sources": [
            {
                "grade": "A", "title": "统计局", "domain": "stats.gov.cn",
                "url": "https://stats.gov.cn/a", "date": "2025-02-28",
                "content_excerpt": "2024年，全国居民人均可支配收入41314元，比上年名义增长5.3%。",
            },
            {
                "grade": "B", "title": "政府网", "domain": "gov.cn",
                "url": "https://gov.cn/b", "date": "2025-02-28",
                "content_excerpt": "2024年全国居民人均可支配收入41314元。",
            },
        ],
    }]


def test_citations_sort_newest_first_when_time_sensitive():
    sample = rows()
    sample[0]["top_sources"][0]["date"] = "2024-01-01"
    sample[0]["top_sources"][1]["date"] = "2026-10-20"
    citations = build_citations(sample, time_sensitive=True)
    assert citations[0]["date"] == "2026-10-20"
    assert citations[-1]["date"] == "2024-01-01"


def test_claim_quote_is_validated_against_source_text():
    citations = build_citations(rows())
    data = {"claims": [{
        "text": "2024年全国居民人均可支配收入为41314元",
        "source_ids": [1],
        "quote": "2024年，全国居民人均可支配收入41314元",
        "source_date": "2020-01-01",
    }]}
    claims, issues = _normalize_claims(data, citations)
    assert claims[0]["quote_valid"] is True
    assert claims[0]["source_date"] == "2025-02-28"
    assert not issues


def test_invalid_claim_quote_is_flagged_not_silently_trusted():
    citations = build_citations(rows())
    data = {"claims": [{
        "text": "不存在的数字",
        "source_ids": [1],
        "quote": "这句原文并不存在",
    }]}
    claims, issues = _normalize_claims(data, citations)
    assert claims[0]["quote_valid"] is False
    assert any(item["reason"] == "quote_not_found" for item in issues)
