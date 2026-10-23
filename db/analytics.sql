-- Analytics views. Safe to re-run: every statement is CREATE OR REPLACE.
--   psql ... < db/analytics.sql

-- One row per unique site. Many domains redirect to the same host
-- (140 Google domains end up on www.google.com), so counting domains
-- would inflate every statistic. The highest-ranked domain represents the site.
CREATE OR REPLACE VIEW sites AS
SELECT DISTINCT ON (host) host, id AS company_id, domain
FROM (
    SELECT id, domain, lower(substring(final_url from '^https?://([^/:]+)')) AS host
    FROM companies
    WHERE crawl_status = 'ok'
) t
ORDER BY host, id;

-- Detections per unique site, with names and categories resolved.
CREATE OR REPLACE VIEW site_technologies AS
SELECT s.host, s.domain, t.name AS technology, t.category, ct.evidence
FROM sites s
JOIN company_technologies ct ON ct.company_id = s.company_id
JOIN technologies t ON t.id = ct.technology_id;
