-- Business questions answered from the crawl. Run with:
--   docker compose exec -T db psql -U techno -d technographics -P pager=off < db/queries.sql

\echo '\n== Q1. Most used technologies, counted per unique site =='
SELECT technology, category, count(*) AS sites,
       round(100.0 * count(*) / (SELECT count(*) FROM sites), 1) AS pct_of_sites
FROM site_technologies
GROUP BY 1, 2 ORDER BY sites DESC LIMIT 15;

\echo '\n== Q2. How much de-duplication changes the counts =='
SELECT t.name AS technology, count(*) AS domains,
       (SELECT count(*) FROM site_technologies st WHERE st.technology = t.name) AS sites
FROM company_technologies ct JOIN technologies t ON t.id = ct.technology_id
GROUP BY t.name
ORDER BY count(*) - (SELECT count(*) FROM site_technologies st WHERE st.technology = t.name) DESC
LIMIT 8;

\echo '\n== Q3. Technologies most often used together (direct evidence only) =='
SELECT a.technology AS tech_a, b.technology AS tech_b, count(*) AS sites
FROM site_technologies a
JOIN site_technologies b ON a.host = b.host AND a.technology < b.technology
WHERE a.evidence NOT LIKE 'implied by%' AND b.evidence NOT LIKE 'implied by%'
GROUP BY 1, 2 ORDER BY sites DESC LIMIT 10;

\echo '\n== Q4. CMS and website-builder market share =='
SELECT technology, count(*) AS sites,
       round(100.0 * count(*) / sum(count(*)) OVER (), 1) AS share_pct
FROM site_technologies
WHERE category IN ('CMS', 'Website builder')
GROUP BY 1 ORDER BY sites DESC;

\echo '\n== Q5. Lead list: tracking tags but no detected cookie-consent tool =='
SELECT s.domain, string_agg(DISTINCT st.technology, ', ') AS trackers
FROM sites s
JOIN site_technologies st ON st.host = s.host
WHERE st.category IN ('Analytics', 'Advertising')
  AND NOT EXISTS (
      SELECT 1 FROM site_technologies c
      WHERE c.host = s.host AND c.category = 'Cookie consent'
  )
GROUP BY s.domain
ORDER BY count(DISTINCT st.technology) DESC, s.domain
LIMIT 15;

\echo '\n== Q6. Query plan: all sites using one technology =='
EXPLAIN ANALYZE
SELECT c.domain
FROM company_technologies ct JOIN companies c ON c.id = ct.company_id
WHERE ct.technology_id = (SELECT id FROM technologies WHERE name = 'Shopify');

\echo '\n== Q7. Technologies used together more often than chance (lift, min 30 sites) =='
-- lift = P(A and B) / (P(A) * P(B)); 1 means independent, higher means real affinity.
WITH direct AS (
    SELECT DISTINCT host, technology FROM site_technologies
    WHERE evidence NOT LIKE 'implied by%'
),
total AS (SELECT count(*)::numeric AS n FROM sites),
freq AS (SELECT technology, count(*) AS cnt FROM direct GROUP BY 1)
SELECT a.technology AS tech_a, b.technology AS tech_b, count(*) AS sites,
       round(count(*) * (SELECT n FROM total) / (fa.cnt * fb.cnt), 1) AS lift
FROM direct a
JOIN direct b ON a.host = b.host AND a.technology < b.technology
JOIN freq fa ON fa.technology = a.technology
JOIN freq fb ON fb.technology = b.technology
GROUP BY 1, 2, fa.cnt, fb.cnt
HAVING count(*) >= 30
ORDER BY lift DESC LIMIT 10;
