from claimlab.contracts import SearchPage
from claimlab.skills.grading import grade_page, is_at_least


def page(domain: str, age_days: int | None = 10) -> SearchPage:
    return SearchPage(title="t", url=f"https://{domain}/x", domain=domain, age_days=age_days)


def test_gov_is_a():
    result = grade_page(page("www.samr.gov.cn"))
    assert result.grade == "A"
    assert result.verifiable == "可核验"


def test_media_platform_selfmedia_ugc():
    assert grade_page(page("www.xinhuanet.com")).grade == "B"
    assert grade_page(page("www.dianping.com")).grade == "C"
    assert grade_page(page("mp.weixin.qq.com")).grade == "D"
    assert grade_page(page("www.xiaohongshu.com")).grade == "E"


def test_unknown_defaults_to_d():
    assert grade_page(page("example.invalid")).grade == "D"


def test_longest_domain_match():
    assert grade_page(page("news.sohu.com")).grade == "B"
    assert grade_page(page("www.sohu.com")).grade == "D"


def test_industry_does_not_upgrade_ugc():
    result = grade_page(page("www.xiaohongshu.com"), industry="gov")
    assert result.grade == "E"


def test_industry_news_does_not_upgrade_ugc():
    result = grade_page(page("www.xiaohongshu.com"), industry="news")
    assert result.grade == "E"


def test_old_evidence_downgrades():
    result = grade_page(page("www.samr.gov.cn", age_days=400))
    assert result.grade == "B"
    assert result.older is True


def test_rank_helpers():
    assert is_at_least("A", "B")
    assert not is_at_least("C", "B")
