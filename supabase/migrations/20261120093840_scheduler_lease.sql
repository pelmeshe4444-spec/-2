CREATE TABLE public.background_leases (
    name text PRIMARY KEY,
    owner uuid NOT NULL,
    expires_at timestamptz NOT NULL
);
ALTER TABLE public.background_leases ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.background_leases FROM anon, authenticated;
GRANT ALL ON public.background_leases TO service_role;
