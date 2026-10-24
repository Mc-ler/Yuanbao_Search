from claimlab.contracts import SearchPage
from claimlab.skills.content import best_excerpt, content_chars


def test_excerpt_prefers_content_terms():
    page = SearchPage(
        title="西安城墙",
        content="西安城墙始建于明代。现存主体为明代修建。周边交通便利。",
        passage="短摘要",
    )
    excerpt = best_excerpt(page, ["明代"])
    assert "明代" in excerpt
    assert len(excerpt) <= 700
    assert content_chars(page) > 0


def test_excerpt_falls_back_to_title():
    page = SearchPage(title="只标题")
    assert best_excerpt(page) == "只标题"
