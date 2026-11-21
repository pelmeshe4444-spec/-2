-- Hosted Supabase supplies these extensions. Vanilla PostgreSQL CI exercises the application schema.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_available_extensions WHERE name = 'pg_cron') THEN
        EXECUTE 'CREATE EXTENSION IF NOT EXISTS pg_cron WITH SCHEMA pg_catalog';
    END IF;
    IF EXISTS (SELECT 1 FROM pg_available_extensions WHERE name = 'pg_net') THEN
        EXECUTE 'CREATE EXTENSION IF NOT EXISTS pg_net WITH SCHEMA extensions';
    END IF;
END
$$;

CREATE OR REPLACE FUNCTION public.attendance_queue_scheduler()
RETURNS bigint
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
DECLARE
    project_url text;
    scheduler_secret text;
    request_id bigint;
BEGIN
    SELECT decrypted_secret INTO project_url
    FROM vault.decrypted_secrets WHERE name = 'attendance_project_url';
    SELECT decrypted_secret INTO scheduler_secret
    FROM vault.decrypted_secrets WHERE name = 'attendance_scheduler_secret';
    IF project_url IS NULL OR scheduler_secret IS NULL THEN
        RAISE EXCEPTION 'Attendance scheduler configuration is incomplete';
    END IF;
    SELECT net.http_post(
        url := project_url || '/functions/v1/report-scheduler',
        headers := jsonb_build_object('Content-Type', 'application/json', 'Authorization', 'Bearer ' || scheduler_secret),
        body := '{}'::jsonb,
        timeout_milliseconds := 150000
    ) INTO request_id;
    RETURN request_id;
END
$$;

REVOKE ALL ON FUNCTION public.attendance_queue_scheduler() FROM PUBLIC, anon, authenticated, service_role;
GRANT EXECUTE ON FUNCTION public.attendance_queue_scheduler() TO postgres;

DO $$
DECLARE
    existing_job bigint;
BEGIN
    IF EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = 'cron') THEN
        EXECUTE 'SELECT jobid FROM cron.job WHERE jobname = ''attendance-reports''' INTO existing_job;
        IF existing_job IS NULL THEN
            EXECUTE 'SELECT cron.schedule(''attendance-reports'', ''* * * * *'', ''SELECT public.attendance_queue_scheduler();'')'
                INTO existing_job;
            EXECUTE 'SELECT cron.alter_job($1, active := false)' USING existing_job;
        END IF;
    END IF;
END
$$;
