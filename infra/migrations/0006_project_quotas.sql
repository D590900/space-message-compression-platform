CREATE TABLE project_quotas (
  tenant_subject text NOT NULL,
  project_id uuid NOT NULL,
  max_monthly_input_bytes bigint NOT NULL DEFAULT 10737418240
    CHECK (max_monthly_input_bytes > 0),
  max_monthly_jobs bigint NOT NULL DEFAULT 10000 CHECK (max_monthly_jobs > 0),
  max_concurrent_jobs integer NOT NULL DEFAULT 100 CHECK (max_concurrent_jobs > 0),
  max_monthly_capsules bigint NOT NULL DEFAULT 1000 CHECK (max_monthly_capsules > 0),
  PRIMARY KEY (tenant_subject, project_id),
  FOREIGN KEY (tenant_subject, project_id) REFERENCES projects (tenant_subject, id)
);

INSERT INTO project_quotas (tenant_subject, project_id)
SELECT tenant_subject, id FROM projects
ON CONFLICT DO NOTHING;
