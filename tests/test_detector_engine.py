from mini_technographics.detector.engine import (
    detect,
    extract_generator,
    load_signatures,
)

SIGS = load_signatures()


def test_signature_names_are_unique():
    names = [s.name for s in SIGS]
    assert len(names) == len(set(names))


def test_every_signature_has_at_least_one_rule():
    for s in SIGS:
        assert s.headers or s.cookies or s.html or s.meta_generator, s.name


def test_detects_from_header_case_insensitively():
    found = detect(SIGS, {"Server": "cloudflare", "CF-RAY": "8a1b2c"}, "")
    assert "Cloudflare" in found


def test_detects_from_html():
    html = '<script src="https://cdn.shopify.com/s/files/theme.js"></script>'
    assert "Shopify" in detect(SIGS, {}, html)


def test_detects_from_meta_generator():
    html = '<meta name="generator" content="WordPress 6.8.1">'
    assert "WordPress" in detect(SIGS, {}, html)


def test_extract_generator_handles_reversed_attribute_order():
    assert extract_generator('<meta content="Drupal 10" name="generator">') == "Drupal 10"


def test_detects_from_cookie():
    found = detect(SIGS, {"set-cookie": "PHPSESSID=abc123; path=/"}, "")
    assert found["PHP"] == "cookie PHPSESSID"


def test_plain_page_has_no_detections():
    assert detect(SIGS, {"content-type": "text/html"}, "<html><body>Hello</body></html>") == {}


def test_implied_technology_is_added_with_its_source():
    found = detect(SIGS, {}, '<script id="__NEXT_DATA__" type="application/json">')
    assert found["React"] == "implied by Next.js"


def test_implies_is_transitive():
    html = '<link rel="stylesheet" href="/wp-content/plugins/woocommerce/style.css">'
    found = detect(SIGS, {}, html)
    assert {"WooCommerce", "WordPress", "PHP"} <= found.keys()


def test_direct_evidence_is_not_overwritten_by_implication():
    html = '<div data-reactroot></div><script id="__NEXT_DATA__"></script>'
    assert detect(SIGS, {}, html)["React"].startswith("html:")
