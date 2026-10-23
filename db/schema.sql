CREATE TABLE companies (
    id           BIGSERIAL PRIMARY KEY,
    domain       TEXT NOT NULL UNIQUE,
    name         TEXT,
    industry     TEXT,
    final_url    TEXT,
    crawl_status TEXT NOT NULL DEFAULT 'pending'
        CHECK (crawl_status IN ('pending', 'ok', 'dns_failed', 'timeout',
                                'http_error', 'blocked', 'error')),
    http_status  INTEGER,
    crawled_at   TIMESTAMPTZ,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE technologies (
    id       SERIAL PRIMARY KEY,
    name     TEXT NOT NULL UNIQUE,
    category TEXT NOT NULL
);

CREATE TABLE company_technologies (
    company_id    BIGINT  NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    technology_id INTEGER NOT NULL REFERENCES technologies(id) ON DELETE CASCADE,
    first_seen    TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen     TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (company_id, technology_id)
);

CREATE TABLE crawl_runs (
    id            BIGSERIAL PRIMARY KEY,
    started_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at   TIMESTAMPTZ,
    domains_total INTEGER,
    pages_ok      INTEGER NOT NULL DEFAULT 0,
    pages_failed  INTEGER NOT NULL DEFAULT 0,
    notes         TEXT
);

CREATE INDEX idx_company_tech_technology ON company_technologies (technology_id);
CREATE INDEX idx_companies_crawl_status  ON companies (crawl_status);
