DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = 'net') THEN
        EXECUTE 'REVOKE ALL ON ALL TABLES IN SCHEMA net FROM PUBLIC, anon, authenticated';
        EXECUTE 'REVOKE ALL ON ALL SEQUENCES IN SCHEMA net FROM PUBLIC, anon, authenticated';
        EXECUTE 'REVOKE ALL ON ALL FUNCTIONS IN SCHEMA net FROM PUBLIC, anon, authenticated';
        EXECUTE 'GRANT ALL ON ALL TABLES IN SCHEMA net TO postgres';
        EXECUTE 'GRANT ALL ON ALL SEQUENCES IN SCHEMA net TO postgres';
        EXECUTE 'GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA net TO postgres';
    END IF;
    IF EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = 'vault') THEN
        EXECUTE 'REVOKE ALL ON ALL TABLES IN SCHEMA vault FROM PUBLIC, anon, authenticated';
    END IF;
END
$$;
