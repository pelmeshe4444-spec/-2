CREATE OR REPLACE FUNCTION public.attendance_queue_scheduler()
RETURNS bigint
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
DECLARE
    project_url text;
    scheduler_secret text;
    request_time text := floor(extract(epoch FROM now()))::bigint::text;
    request_nonce text := gen_random_uuid()::text;
    signature text;
    request_id bigint;
BEGIN
    SELECT decrypted_secret INTO project_url
    FROM vault.decrypted_secrets WHERE name = 'attendance_project_url';
    SELECT decrypted_secret INTO scheduler_secret
    FROM vault.decrypted_secrets WHERE name = 'attendance_scheduler_secret';
    IF project_url IS NULL OR scheduler_secret IS NULL THEN
        RAISE EXCEPTION 'Attendance scheduler configuration is incomplete';
    END IF;
    signature := encode(extensions.hmac(
        'attendance-scheduler' || chr(10) || request_time || chr(10) || request_nonce,
        scheduler_secret, 'sha256'), 'hex');
    SELECT net.http_post(
        url := project_url || '/functions/v1/report-scheduler',
        headers := jsonb_build_object(
            'Content-Type', 'application/json',
            'X-Attendance-Time', request_time,
            'X-Attendance-Nonce', request_nonce,
            'X-Attendance-Signature', signature
        ),
        body := '{}'::jsonb,
        timeout_milliseconds := 150000
    ) INTO request_id;
    RETURN request_id;
END
$$;
REVOKE ALL ON FUNCTION public.attendance_queue_scheduler() FROM PUBLIC, anon, authenticated, service_role;
GRANT EXECUTE ON FUNCTION public.attendance_queue_scheduler() TO postgres;
