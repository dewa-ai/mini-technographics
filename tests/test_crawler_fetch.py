import httpx

from mini_technographics.crawler.fetch import _classify_response


def _response(status: int, url: str) -> httpx.Response:
    return httpx.Response(status, request=httpx.Request("GET", url))


def test_isp_block_page_is_recognised():
    assert _classify_response(_response(200, "https://internet-positif.info/")) == "isp_blocked"


def test_normal_responses_are_classified_by_status():
    assert _classify_response(_response(200, "https://example.com/")) == "ok"
    assert _classify_response(_response(403, "https://example.com/")) == "blocked"
    assert _classify_response(_response(500, "https://example.com/")) == "http_error"
