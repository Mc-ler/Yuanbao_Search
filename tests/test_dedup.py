import random

from claimlab.contracts import SearchPage
from claimlab.skills.dedup import cluster_pages, jaccard, shingles


def make_page(url: str, text: str) -> SearchPage:
    return SearchPage(title=text[:40], url=url, domain=url.split("/")[2], passage=text)


def test_reposts_cluster_once():
    text = "这家店人均六十八元，周一闭店，排队四十分钟，服务员态度特别差。"
    pages = [
        make_page("https://a.example/x", text),
        make_page("https://b.example/x", text),
        make_page("https://c.example/x", text),
        make_page("https://d.example/x", "西安城墙今天正常开放，门票需要提前预约。"),
    ]
    result = cluster_pages(pages, 0.65)
    assert len(result.unique_pages) == 4
    sizes = sorted(cluster.size for cluster in result.clusters)
    assert sizes == [1, 3]
    biggest = max(result.clusters, key=lambda item: item.size)
    assert biggest.size == 3
    assert len(biggest.domains) == 3


def test_order_invariance():
    text = "同一段通稿被多个站点转载，标题不同但摘要几乎一样。"
    pages = [make_page(f"https://{name}.example/x", text) for name in ("a", "b", "c")]
    pages.append(make_page("https://z.example/x", "完全无关的另一个页面内容。"))
    first = cluster_pages(pages, 0.65)
    random.Random(42).shuffle(pages)
    second = cluster_pages(pages, 0.65)
    assert [c.cluster_id for c in first.clusters] == [c.cluster_id for c in second.clusters]
    assert [c.member_ids for c in first.clusters] == [c.member_ids for c in second.clusters]


def test_duplicate_url_kept_once():
    pages = [make_page("https://a.example/x", "甲"), make_page("https://a.example/x", "甲")]
    result = cluster_pages(pages, 0.65)
    assert len(result.unique_pages) == 1


def test_jaccard_bounds():
    assert jaccard(set(), set()) == 1.0
    assert jaccard({"a"}, set()) == 0.0
    assert jaccard(shingles("四个字"), shingles("四个字")) == 1.0
