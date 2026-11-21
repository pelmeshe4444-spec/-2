-- Attendance schema exported from the verified Render snapshot.
CREATE TABLE public.alembic_version (
    version_num character varying(32) NOT NULL
);



CREATE TABLE public.announcements (
    id integer NOT NULL,
    request_id character varying(32) NOT NULL,
    class_ids json NOT NULL,
    message character varying(500) NOT NULL,
    created_at timestamp without time zone NOT NULL
);



CREATE SEQUENCE public.announcements_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;



ALTER SEQUENCE public.announcements_id_seq OWNED BY public.announcements.id;



CREATE TABLE public.attendance (
    id integer NOT NULL,
    student_id integer NOT NULL,
    date date NOT NULL,
    status integer NOT NULL,
    reason character varying(300),
    marked_by integer NOT NULL,
    updated_at timestamp without time zone NOT NULL,
    CONSTRAINT ck_attendance_status CHECK (((status >= 0) AND (status <= 4)))
);



CREATE TABLE public.attendance_history (
    id integer NOT NULL,
    student_id integer NOT NULL,
    class_id integer NOT NULL,
    date date NOT NULL,
    actor_id integer NOT NULL,
    before_status integer NOT NULL,
    after_status integer NOT NULL,
    before_reason character varying(300),
    after_reason character varying(300),
    changed_at timestamp without time zone NOT NULL
);



CREATE SEQUENCE public.attendance_history_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;



ALTER SEQUENCE public.attendance_history_id_seq OWNED BY public.attendance_history.id;



CREATE SEQUENCE public.attendance_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;



ALTER SEQUENCE public.attendance_id_seq OWNED BY public.attendance.id;



CREATE TABLE public.audit_logs (
    id integer NOT NULL,
    actor_id integer,
    action character varying(40) NOT NULL,
    entity_type character varying(32) NOT NULL,
    entity_id integer,
    "timestamp" timestamp without time zone NOT NULL,
    details character varying(300)
);



CREATE SEQUENCE public.audit_logs_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;



ALTER SEQUENCE public.audit_logs_id_seq OWNED BY public.audit_logs.id;



CREATE TABLE public.class_join_requests (
    id integer NOT NULL,
    user_id integer NOT NULL,
    class_id integer NOT NULL,
    pending_user_id integer,
    status character varying(12) NOT NULL,
    requested_at timestamp without time zone NOT NULL,
    decided_at timestamp without time zone,
    decided_by integer,
    CONSTRAINT ck_join_status CHECK (((status)::text = ANY ((ARRAY['PENDING'::character varying, 'APPROVED'::character varying, 'REJECTED'::character varying, 'BLOCKED'::character varying])::text[])))
);



CREATE SEQUENCE public.class_join_requests_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;



ALTER SEQUENCE public.class_join_requests_id_seq OWNED BY public.class_join_requests.id;



CREATE TABLE public.class_memberships (
    user_id integer NOT NULL,
    class_id integer NOT NULL,
    notify_schedule boolean NOT NULL,
    approved_at timestamp without time zone NOT NULL
);



CREATE TABLE public.class_timetables (
    id integer NOT NULL,
    class_id integer NOT NULL,
    name character varying(80) NOT NULL,
    cycle character varying(1) NOT NULL,
    effective_from date NOT NULL,
    effective_to date,
    is_active boolean NOT NULL,
    revision integer NOT NULL,
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone NOT NULL
);



CREATE SEQUENCE public.class_timetables_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;



ALTER SEQUENCE public.class_timetables_id_seq OWNED BY public.class_timetables.id;



CREATE TABLE public.classes (
    id integer NOT NULL,
    name character varying(32) NOT NULL,
    name_key character varying(64) NOT NULL,
    is_active boolean NOT NULL,
    archived_on date
);



CREATE SEQUENCE public.classes_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;



ALTER SEQUENCE public.classes_id_seq OWNED BY public.classes.id;



CREATE TABLE public.enrollments (
    student_id integer NOT NULL,
    starts_on date NOT NULL,
    class_id integer NOT NULL,
    ends_before date
);



CREATE TABLE public.lesson_time_slots (
    id integer NOT NULL,
    class_id integer NOT NULL,
    shift character varying(32) NOT NULL,
    lesson_number integer NOT NULL,
    start_time character varying(5) NOT NULL,
    end_time character varying(5) NOT NULL
);



CREATE SEQUENCE public.lesson_time_slots_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;



ALTER SEQUENCE public.lesson_time_slots_id_seq OWNED BY public.lesson_time_slots.id;



CREATE TABLE public.manager_assignments (
    user_id integer NOT NULL,
    class_id integer NOT NULL,
    can_view_history boolean NOT NULL,
    can_edit_timetable boolean DEFAULT false NOT NULL,
    can_edit_history boolean DEFAULT false NOT NULL,
    can_view_statistics boolean DEFAULT false NOT NULL,
    can_view_reports boolean DEFAULT false NOT NULL,
    can_send_reports boolean DEFAULT true NOT NULL
);



CREATE TABLE public.notifications (
    id integer NOT NULL,
    recipient_id integer NOT NULL,
    class_id integer,
    category character varying(24) NOT NULL,
    message character varying(500) NOT NULL,
    status character varying(16) NOT NULL,
    created_at timestamp without time zone NOT NULL,
    attempted_at timestamp without time zone,
    read_at timestamp without time zone,
    announcement_id integer
);



CREATE SEQUENCE public.notifications_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;



ALTER SEQUENCE public.notifications_id_seq OWNED BY public.notifications.id;



CREATE TABLE public.report_deliveries (
    id integer NOT NULL,
    schedule_id integer NOT NULL,
    recipient_id integer NOT NULL,
    report_date date NOT NULL,
    dispatch_key character varying(40) NOT NULL,
    status character varying(16) NOT NULL,
    created_at timestamp without time zone NOT NULL,
    sent_at timestamp without time zone,
    error_message character varying(160),
    parts_sent integer NOT NULL,
    parts_total integer NOT NULL,
    body character varying,
    attempts integer DEFAULT 1 NOT NULL,
    retry_at timestamp without time zone,
    initiated_by integer,
    telegram_message_id bigint
);



CREATE SEQUENCE public.report_deliveries_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;



ALTER SEQUENCE public.report_deliveries_id_seq OWNED BY public.report_deliveries.id;



CREATE TABLE public.report_recipients (
    user_id integer NOT NULL,
    class_id integer NOT NULL
);



CREATE TABLE public.report_schedules (
    id integer NOT NULL,
    class_id integer NOT NULL,
    "time" character varying(5) NOT NULL,
    timezone character varying(64) NOT NULL,
    weekdays character varying(7) NOT NULL,
    is_enabled boolean NOT NULL,
    reminder_one character varying(5),
    reminder_two character varying(5),
    deleted boolean DEFAULT false NOT NULL
);



CREATE SEQUENCE public.report_schedules_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;



ALTER SEQUENCE public.report_schedules_id_seq OWNED BY public.report_schedules.id;



CREATE TABLE public.school_settings (
    id integer NOT NULL,
    name character varying(120) NOT NULL,
    preferences json
);



CREATE SEQUENCE public.school_settings_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;



ALTER SEQUENCE public.school_settings_id_seq OWNED BY public.school_settings.id;



CREATE TABLE public.students (
    id integer NOT NULL,
    first_name character varying(48) NOT NULL,
    last_name character varying(48) NOT NULL,
    class_id integer NOT NULL,
    active_name_key character varying(765),
    is_active boolean NOT NULL,
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone NOT NULL,
    full_name character varying(255) DEFAULT ''::character varying NOT NULL
);



CREATE SEQUENCE public.students_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;



ALTER SEQUENCE public.students_id_seq OWNED BY public.students.id;



CREATE TABLE public.subjects (
    id integer NOT NULL,
    name character varying(80) NOT NULL,
    name_key character varying(160) NOT NULL,
    color character varying(7) NOT NULL,
    icon character varying(24) NOT NULL,
    is_active boolean NOT NULL,
    created_at timestamp without time zone NOT NULL
);



CREATE SEQUENCE public.subjects_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;



ALTER SEQUENCE public.subjects_id_seq OWNED BY public.subjects.id;



CREATE TABLE public.system_events (
    id integer NOT NULL,
    operation character varying(24) NOT NULL,
    success boolean NOT NULL,
    occurred_at timestamp without time zone NOT NULL
);



CREATE SEQUENCE public.system_events_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;



ALTER SEQUENCE public.system_events_id_seq OWNED BY public.system_events.id;



CREATE TABLE public.timetable_change_history (
    id integer NOT NULL,
    class_id integer NOT NULL,
    actor_id integer NOT NULL,
    target character varying(12) NOT NULL,
    plan_key character varying(24) NOT NULL,
    before json NOT NULL,
    after json NOT NULL,
    changed_at timestamp without time zone NOT NULL
);



CREATE SEQUENCE public.timetable_change_history_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;



ALTER SEQUENCE public.timetable_change_history_id_seq OWNED BY public.timetable_change_history.id;



CREATE TABLE public.timetable_exceptions (
    id integer NOT NULL,
    class_id integer NOT NULL,
    date date NOT NULL,
    action character varying(12) NOT NULL,
    lessons json NOT NULL,
    comment character varying(250),
    revision integer NOT NULL,
    created_by integer NOT NULL,
    created_at timestamp without time zone NOT NULL
);



CREATE SEQUENCE public.timetable_exceptions_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;



ALTER SEQUENCE public.timetable_exceptions_id_seq OWNED BY public.timetable_exceptions.id;



CREATE TABLE public.timetable_lessons (
    id integer NOT NULL,
    timetable_id integer NOT NULL,
    subject_id integer NOT NULL,
    weekday integer NOT NULL,
    lesson_number integer NOT NULL,
    start_time character varying(5) NOT NULL,
    end_time character varying(5) NOT NULL,
    teacher_name character varying(100),
    classroom character varying(40),
    comment character varying(250),
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone NOT NULL,
    CONSTRAINT ck_lesson_times CHECK ((((weekday >= 0) AND (weekday <= 6)) AND ((lesson_number >= 1) AND (lesson_number <= 20)) AND ((start_time)::text < (end_time)::text)))
);



CREATE SEQUENCE public.timetable_lessons_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;



ALTER SEQUENCE public.timetable_lessons_id_seq OWNED BY public.timetable_lessons.id;



CREATE TABLE public.user_roles (
    user_id integer NOT NULL,
    role character varying(24) NOT NULL,
    created_at timestamp without time zone NOT NULL,
    CONSTRAINT ck_delegated_role CHECK (((role)::text = ANY ((ARRAY['MANAGER'::character varying, 'REPORT_RECIPIENT'::character varying])::text[])))
);



CREATE TABLE public.users (
    id integer NOT NULL,
    telegram_id bigint NOT NULL,
    username character varying(64),
    full_name character varying(160),
    started_at timestamp without time zone,
    created_at timestamp without time zone NOT NULL,
    blocked boolean DEFAULT false NOT NULL
);



CREATE SEQUENCE public.users_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;



ALTER SEQUENCE public.users_id_seq OWNED BY public.users.id;



ALTER TABLE ONLY public.announcements ALTER COLUMN id SET DEFAULT nextval('public.announcements_id_seq'::regclass);



ALTER TABLE ONLY public.attendance ALTER COLUMN id SET DEFAULT nextval('public.attendance_id_seq'::regclass);



ALTER TABLE ONLY public.attendance_history ALTER COLUMN id SET DEFAULT nextval('public.attendance_history_id_seq'::regclass);



ALTER TABLE ONLY public.audit_logs ALTER COLUMN id SET DEFAULT nextval('public.audit_logs_id_seq'::regclass);



ALTER TABLE ONLY public.class_join_requests ALTER COLUMN id SET DEFAULT nextval('public.class_join_requests_id_seq'::regclass);



ALTER TABLE ONLY public.class_timetables ALTER COLUMN id SET DEFAULT nextval('public.class_timetables_id_seq'::regclass);



ALTER TABLE ONLY public.classes ALTER COLUMN id SET DEFAULT nextval('public.classes_id_seq'::regclass);



ALTER TABLE ONLY public.lesson_time_slots ALTER COLUMN id SET DEFAULT nextval('public.lesson_time_slots_id_seq'::regclass);



ALTER TABLE ONLY public.notifications ALTER COLUMN id SET DEFAULT nextval('public.notifications_id_seq'::regclass);



ALTER TABLE ONLY public.report_deliveries ALTER COLUMN id SET DEFAULT nextval('public.report_deliveries_id_seq'::regclass);



ALTER TABLE ONLY public.report_schedules ALTER COLUMN id SET DEFAULT nextval('public.report_schedules_id_seq'::regclass);



ALTER TABLE ONLY public.school_settings ALTER COLUMN id SET DEFAULT nextval('public.school_settings_id_seq'::regclass);



ALTER TABLE ONLY public.students ALTER COLUMN id SET DEFAULT nextval('public.students_id_seq'::regclass);



ALTER TABLE ONLY public.subjects ALTER COLUMN id SET DEFAULT nextval('public.subjects_id_seq'::regclass);



ALTER TABLE ONLY public.system_events ALTER COLUMN id SET DEFAULT nextval('public.system_events_id_seq'::regclass);



ALTER TABLE ONLY public.timetable_change_history ALTER COLUMN id SET DEFAULT nextval('public.timetable_change_history_id_seq'::regclass);



ALTER TABLE ONLY public.timetable_exceptions ALTER COLUMN id SET DEFAULT nextval('public.timetable_exceptions_id_seq'::regclass);



ALTER TABLE ONLY public.timetable_lessons ALTER COLUMN id SET DEFAULT nextval('public.timetable_lessons_id_seq'::regclass);



ALTER TABLE ONLY public.users ALTER COLUMN id SET DEFAULT nextval('public.users_id_seq'::regclass);



ALTER TABLE ONLY public.alembic_version
    ADD CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num);



ALTER TABLE ONLY public.announcements
    ADD CONSTRAINT announcements_pkey PRIMARY KEY (id);



ALTER TABLE ONLY public.announcements
    ADD CONSTRAINT announcements_request_id_key UNIQUE (request_id);



ALTER TABLE ONLY public.attendance_history
    ADD CONSTRAINT attendance_history_pkey PRIMARY KEY (id);



ALTER TABLE ONLY public.attendance
    ADD CONSTRAINT attendance_pkey PRIMARY KEY (id);



ALTER TABLE ONLY public.audit_logs
    ADD CONSTRAINT audit_logs_pkey PRIMARY KEY (id);



ALTER TABLE ONLY public.class_join_requests
    ADD CONSTRAINT class_join_requests_pending_user_id_key UNIQUE (pending_user_id);



ALTER TABLE ONLY public.class_join_requests
    ADD CONSTRAINT class_join_requests_pkey PRIMARY KEY (id);



ALTER TABLE ONLY public.class_memberships
    ADD CONSTRAINT class_memberships_pkey PRIMARY KEY (user_id);



ALTER TABLE ONLY public.class_timetables
    ADD CONSTRAINT class_timetables_pkey PRIMARY KEY (id);



ALTER TABLE ONLY public.classes
    ADD CONSTRAINT classes_name_key_key UNIQUE (name_key);



ALTER TABLE ONLY public.classes
    ADD CONSTRAINT classes_pkey PRIMARY KEY (id);



ALTER TABLE ONLY public.enrollments
    ADD CONSTRAINT enrollments_pkey PRIMARY KEY (student_id, starts_on);



ALTER TABLE ONLY public.lesson_time_slots
    ADD CONSTRAINT lesson_time_slots_pkey PRIMARY KEY (id);



ALTER TABLE ONLY public.manager_assignments
    ADD CONSTRAINT manager_assignments_pkey PRIMARY KEY (user_id, class_id);



ALTER TABLE ONLY public.notifications
    ADD CONSTRAINT notifications_pkey PRIMARY KEY (id);



ALTER TABLE ONLY public.report_deliveries
    ADD CONSTRAINT report_deliveries_pkey PRIMARY KEY (id);



ALTER TABLE ONLY public.report_recipients
    ADD CONSTRAINT report_recipients_pkey PRIMARY KEY (user_id, class_id);



ALTER TABLE ONLY public.report_schedules
    ADD CONSTRAINT report_schedules_class_id_key UNIQUE (class_id);



ALTER TABLE ONLY public.report_schedules
    ADD CONSTRAINT report_schedules_pkey PRIMARY KEY (id);



ALTER TABLE ONLY public.school_settings
    ADD CONSTRAINT school_settings_pkey PRIMARY KEY (id);



ALTER TABLE ONLY public.students
    ADD CONSTRAINT students_pkey PRIMARY KEY (id);



ALTER TABLE ONLY public.subjects
    ADD CONSTRAINT subjects_name_key_key UNIQUE (name_key);



ALTER TABLE ONLY public.subjects
    ADD CONSTRAINT subjects_pkey PRIMARY KEY (id);



ALTER TABLE ONLY public.system_events
    ADD CONSTRAINT system_events_pkey PRIMARY KEY (id);



ALTER TABLE ONLY public.timetable_change_history
    ADD CONSTRAINT timetable_change_history_pkey PRIMARY KEY (id);



ALTER TABLE ONLY public.timetable_exceptions
    ADD CONSTRAINT timetable_exceptions_pkey PRIMARY KEY (id);



ALTER TABLE ONLY public.timetable_lessons
    ADD CONSTRAINT timetable_lessons_pkey PRIMARY KEY (id);



ALTER TABLE ONLY public.attendance
    ADD CONSTRAINT uq_attendance_student_date UNIQUE (student_id, date);



ALTER TABLE ONLY public.lesson_time_slots
    ADD CONSTRAINT uq_bell_slot UNIQUE (class_id, shift, lesson_number);



ALTER TABLE ONLY public.timetable_exceptions
    ADD CONSTRAINT uq_class_exception_date UNIQUE (class_id, date);



ALTER TABLE ONLY public.report_deliveries
    ADD CONSTRAINT uq_delivery_dispatch UNIQUE (schedule_id, recipient_id, report_date, dispatch_key);



ALTER TABLE ONLY public.timetable_lessons
    ADD CONSTRAINT uq_lesson_number UNIQUE (timetable_id, weekday, lesson_number);



ALTER TABLE ONLY public.students
    ADD CONSTRAINT uq_student_active_name UNIQUE (class_id, active_name_key);



ALTER TABLE ONLY public.class_timetables
    ADD CONSTRAINT uq_timetable_effective UNIQUE (class_id, cycle, effective_from);



ALTER TABLE ONLY public.user_roles
    ADD CONSTRAINT user_roles_pkey PRIMARY KEY (user_id, role);



ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_pkey PRIMARY KEY (id);



ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_telegram_id_key UNIQUE (telegram_id);



CREATE INDEX ix_attendance_date ON public.attendance USING btree (date);



CREATE INDEX ix_attendance_history_class_id ON public.attendance_history USING btree (class_id);



CREATE INDEX ix_attendance_history_student_id ON public.attendance_history USING btree (student_id);



CREATE INDEX ix_audit_logs_timestamp ON public.audit_logs USING btree ("timestamp");



CREATE INDEX ix_class_join_requests_status ON public.class_join_requests USING btree (status);



CREATE INDEX ix_class_join_requests_user_id ON public.class_join_requests USING btree (user_id);



CREATE INDEX ix_class_memberships_class_id ON public.class_memberships USING btree (class_id);



CREATE INDEX ix_class_timetables_class_id ON public.class_timetables USING btree (class_id);



CREATE INDEX ix_delivery_class_latest ON public.report_deliveries USING btree (schedule_id, report_date, sent_at);



CREATE INDEX ix_delivery_status_time ON public.report_deliveries USING btree (status, created_at);



CREATE INDEX ix_enrollment_class_period ON public.enrollments USING btree (class_id, starts_on, ends_before);



CREATE INDEX ix_manager_assignments_class_id ON public.manager_assignments USING btree (class_id);



CREATE INDEX ix_notifications_announcement_id ON public.notifications USING btree (announcement_id);



CREATE INDEX ix_notifications_recipient_id ON public.notifications USING btree (recipient_id);



CREATE INDEX ix_notifications_status ON public.notifications USING btree (status);



CREATE INDEX ix_report_recipients_class_id ON public.report_recipients USING btree (class_id);



CREATE INDEX ix_students_class_id ON public.students USING btree (class_id);



CREATE INDEX ix_timetable_change_history_class_id ON public.timetable_change_history USING btree (class_id);



CREATE INDEX ix_timetable_lessons_timetable_id ON public.timetable_lessons USING btree (timetable_id);



ALTER TABLE ONLY public.attendance_history
    ADD CONSTRAINT attendance_history_actor_id_fkey FOREIGN KEY (actor_id) REFERENCES public.users(id);



ALTER TABLE ONLY public.attendance_history
    ADD CONSTRAINT attendance_history_class_id_fkey FOREIGN KEY (class_id) REFERENCES public.classes(id);



ALTER TABLE ONLY public.attendance_history
    ADD CONSTRAINT attendance_history_student_id_fkey FOREIGN KEY (student_id) REFERENCES public.students(id);



ALTER TABLE ONLY public.attendance
    ADD CONSTRAINT attendance_marked_by_fkey FOREIGN KEY (marked_by) REFERENCES public.users(id);



ALTER TABLE ONLY public.attendance
    ADD CONSTRAINT attendance_student_id_fkey FOREIGN KEY (student_id) REFERENCES public.students(id);



ALTER TABLE ONLY public.audit_logs
    ADD CONSTRAINT audit_logs_actor_id_fkey FOREIGN KEY (actor_id) REFERENCES public.users(id);



ALTER TABLE ONLY public.class_join_requests
    ADD CONSTRAINT class_join_requests_class_id_fkey FOREIGN KEY (class_id) REFERENCES public.classes(id);



ALTER TABLE ONLY public.class_join_requests
    ADD CONSTRAINT class_join_requests_decided_by_fkey FOREIGN KEY (decided_by) REFERENCES public.users(id);



ALTER TABLE ONLY public.class_join_requests
    ADD CONSTRAINT class_join_requests_pending_user_id_fkey FOREIGN KEY (pending_user_id) REFERENCES public.users(id);



ALTER TABLE ONLY public.class_join_requests
    ADD CONSTRAINT class_join_requests_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id);



ALTER TABLE ONLY public.class_memberships
    ADD CONSTRAINT class_memberships_class_id_fkey FOREIGN KEY (class_id) REFERENCES public.classes(id);



ALTER TABLE ONLY public.class_memberships
    ADD CONSTRAINT class_memberships_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id);



ALTER TABLE ONLY public.class_timetables
    ADD CONSTRAINT class_timetables_class_id_fkey FOREIGN KEY (class_id) REFERENCES public.classes(id);



ALTER TABLE ONLY public.enrollments
    ADD CONSTRAINT enrollments_class_id_fkey FOREIGN KEY (class_id) REFERENCES public.classes(id);



ALTER TABLE ONLY public.enrollments
    ADD CONSTRAINT enrollments_student_id_fkey FOREIGN KEY (student_id) REFERENCES public.students(id);



ALTER TABLE ONLY public.notifications
    ADD CONSTRAINT fk_notification_announcement FOREIGN KEY (announcement_id) REFERENCES public.announcements(id);



ALTER TABLE ONLY public.lesson_time_slots
    ADD CONSTRAINT lesson_time_slots_class_id_fkey FOREIGN KEY (class_id) REFERENCES public.classes(id);



ALTER TABLE ONLY public.manager_assignments
    ADD CONSTRAINT manager_assignments_class_id_fkey FOREIGN KEY (class_id) REFERENCES public.classes(id);



ALTER TABLE ONLY public.manager_assignments
    ADD CONSTRAINT manager_assignments_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id);



ALTER TABLE ONLY public.notifications
    ADD CONSTRAINT notifications_class_id_fkey FOREIGN KEY (class_id) REFERENCES public.classes(id);



ALTER TABLE ONLY public.notifications
    ADD CONSTRAINT notifications_recipient_id_fkey FOREIGN KEY (recipient_id) REFERENCES public.users(id);



ALTER TABLE ONLY public.report_deliveries
    ADD CONSTRAINT report_deliveries_initiated_by_fkey FOREIGN KEY (initiated_by) REFERENCES public.users(id);



ALTER TABLE ONLY public.report_deliveries
    ADD CONSTRAINT report_deliveries_recipient_id_fkey FOREIGN KEY (recipient_id) REFERENCES public.users(id);



ALTER TABLE ONLY public.report_deliveries
    ADD CONSTRAINT report_deliveries_schedule_id_fkey FOREIGN KEY (schedule_id) REFERENCES public.report_schedules(id);



ALTER TABLE ONLY public.report_recipients
    ADD CONSTRAINT report_recipients_class_id_fkey FOREIGN KEY (class_id) REFERENCES public.classes(id);



ALTER TABLE ONLY public.report_recipients
    ADD CONSTRAINT report_recipients_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id);



ALTER TABLE ONLY public.report_schedules
    ADD CONSTRAINT report_schedules_class_id_fkey FOREIGN KEY (class_id) REFERENCES public.classes(id);



ALTER TABLE ONLY public.students
    ADD CONSTRAINT students_class_id_fkey FOREIGN KEY (class_id) REFERENCES public.classes(id);



ALTER TABLE ONLY public.timetable_change_history
    ADD CONSTRAINT timetable_change_history_actor_id_fkey FOREIGN KEY (actor_id) REFERENCES public.users(id);



ALTER TABLE ONLY public.timetable_change_history
    ADD CONSTRAINT timetable_change_history_class_id_fkey FOREIGN KEY (class_id) REFERENCES public.classes(id);



ALTER TABLE ONLY public.timetable_exceptions
    ADD CONSTRAINT timetable_exceptions_class_id_fkey FOREIGN KEY (class_id) REFERENCES public.classes(id);



ALTER TABLE ONLY public.timetable_exceptions
    ADD CONSTRAINT timetable_exceptions_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.users(id);



ALTER TABLE ONLY public.timetable_lessons
    ADD CONSTRAINT timetable_lessons_subject_id_fkey FOREIGN KEY (subject_id) REFERENCES public.subjects(id);



ALTER TABLE ONLY public.timetable_lessons
    ADD CONSTRAINT timetable_lessons_timetable_id_fkey FOREIGN KEY (timetable_id) REFERENCES public.class_timetables(id);



ALTER TABLE ONLY public.user_roles
    ADD CONSTRAINT user_roles_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id);
ALTER TABLE public."announcements" ALTER COLUMN "created_at" SET DEFAULT timezone('UTC', now());
ALTER TABLE public."classes" ALTER COLUMN "is_active" SET DEFAULT true;
ALTER TABLE public."subjects" ALTER COLUMN "is_active" SET DEFAULT true;
ALTER TABLE public."subjects" ALTER COLUMN "created_at" SET DEFAULT timezone('UTC', now());
ALTER TABLE public."system_events" ALTER COLUMN "occurred_at" SET DEFAULT timezone('UTC', now());
ALTER TABLE public."users" ALTER COLUMN "blocked" SET DEFAULT false;
ALTER TABLE public."users" ALTER COLUMN "created_at" SET DEFAULT timezone('UTC', now());
ALTER TABLE public."audit_logs" ALTER COLUMN "timestamp" SET DEFAULT timezone('UTC', now());
ALTER TABLE public."class_join_requests" ALTER COLUMN "status" SET DEFAULT 'PENDING';
ALTER TABLE public."class_join_requests" ALTER COLUMN "requested_at" SET DEFAULT timezone('UTC', now());
ALTER TABLE public."class_memberships" ALTER COLUMN "notify_schedule" SET DEFAULT false;
ALTER TABLE public."class_memberships" ALTER COLUMN "approved_at" SET DEFAULT timezone('UTC', now());
ALTER TABLE public."class_timetables" ALTER COLUMN "is_active" SET DEFAULT true;
ALTER TABLE public."class_timetables" ALTER COLUMN "revision" SET DEFAULT 0;
ALTER TABLE public."class_timetables" ALTER COLUMN "created_at" SET DEFAULT timezone('UTC', now());
ALTER TABLE public."class_timetables" ALTER COLUMN "updated_at" SET DEFAULT timezone('UTC', now());
ALTER TABLE public."manager_assignments" ALTER COLUMN "can_view_history" SET DEFAULT false;
ALTER TABLE public."manager_assignments" ALTER COLUMN "can_edit_timetable" SET DEFAULT false;
ALTER TABLE public."manager_assignments" ALTER COLUMN "can_edit_history" SET DEFAULT false;
ALTER TABLE public."manager_assignments" ALTER COLUMN "can_view_statistics" SET DEFAULT false;
ALTER TABLE public."manager_assignments" ALTER COLUMN "can_view_reports" SET DEFAULT false;
ALTER TABLE public."manager_assignments" ALTER COLUMN "can_send_reports" SET DEFAULT true;
ALTER TABLE public."notifications" ALTER COLUMN "created_at" SET DEFAULT timezone('UTC', now());
ALTER TABLE public."report_schedules" ALTER COLUMN "time" SET DEFAULT '08:30';
ALTER TABLE public."report_schedules" ALTER COLUMN "weekdays" SET DEFAULT '01234';
ALTER TABLE public."report_schedules" ALTER COLUMN "is_enabled" SET DEFAULT false;
ALTER TABLE public."report_schedules" ALTER COLUMN "deleted" SET DEFAULT false;
ALTER TABLE public."students" ALTER COLUMN "first_name" SET DEFAULT '';
ALTER TABLE public."students" ALTER COLUMN "last_name" SET DEFAULT '';
ALTER TABLE public."students" ALTER COLUMN "is_active" SET DEFAULT true;
ALTER TABLE public."students" ALTER COLUMN "created_at" SET DEFAULT timezone('UTC', now());
ALTER TABLE public."students" ALTER COLUMN "updated_at" SET DEFAULT timezone('UTC', now());
ALTER TABLE public."timetable_change_history" ALTER COLUMN "changed_at" SET DEFAULT timezone('UTC', now());
ALTER TABLE public."timetable_exceptions" ALTER COLUMN "revision" SET DEFAULT 0;
ALTER TABLE public."timetable_exceptions" ALTER COLUMN "created_at" SET DEFAULT timezone('UTC', now());
ALTER TABLE public."user_roles" ALTER COLUMN "created_at" SET DEFAULT timezone('UTC', now());
ALTER TABLE public."attendance" ALTER COLUMN "updated_at" SET DEFAULT timezone('UTC', now());
ALTER TABLE public."attendance_history" ALTER COLUMN "changed_at" SET DEFAULT timezone('UTC', now());
ALTER TABLE public."report_deliveries" ALTER COLUMN "status" SET DEFAULT 'sending';
ALTER TABLE public."report_deliveries" ALTER COLUMN "created_at" SET DEFAULT timezone('UTC', now());
ALTER TABLE public."report_deliveries" ALTER COLUMN "parts_sent" SET DEFAULT 0;
ALTER TABLE public."report_deliveries" ALTER COLUMN "parts_total" SET DEFAULT 0;
ALTER TABLE public."report_deliveries" ALTER COLUMN "attempts" SET DEFAULT 1;
ALTER TABLE public."timetable_lessons" ALTER COLUMN "created_at" SET DEFAULT timezone('UTC', now());
ALTER TABLE public."timetable_lessons" ALTER COLUMN "updated_at" SET DEFAULT timezone('UTC', now());
ALTER TABLE public."announcements" ENABLE ROW LEVEL SECURITY;
ALTER TABLE public."classes" ENABLE ROW LEVEL SECURITY;
ALTER TABLE public."school_settings" ENABLE ROW LEVEL SECURITY;
ALTER TABLE public."subjects" ENABLE ROW LEVEL SECURITY;
ALTER TABLE public."system_events" ENABLE ROW LEVEL SECURITY;
ALTER TABLE public."users" ENABLE ROW LEVEL SECURITY;
ALTER TABLE public."audit_logs" ENABLE ROW LEVEL SECURITY;
ALTER TABLE public."class_join_requests" ENABLE ROW LEVEL SECURITY;
ALTER TABLE public."class_memberships" ENABLE ROW LEVEL SECURITY;
ALTER TABLE public."class_timetables" ENABLE ROW LEVEL SECURITY;
ALTER TABLE public."lesson_time_slots" ENABLE ROW LEVEL SECURITY;
ALTER TABLE public."manager_assignments" ENABLE ROW LEVEL SECURITY;
ALTER TABLE public."notifications" ENABLE ROW LEVEL SECURITY;
ALTER TABLE public."report_recipients" ENABLE ROW LEVEL SECURITY;
ALTER TABLE public."report_schedules" ENABLE ROW LEVEL SECURITY;
ALTER TABLE public."students" ENABLE ROW LEVEL SECURITY;
ALTER TABLE public."timetable_change_history" ENABLE ROW LEVEL SECURITY;
ALTER TABLE public."timetable_exceptions" ENABLE ROW LEVEL SECURITY;
ALTER TABLE public."user_roles" ENABLE ROW LEVEL SECURITY;
ALTER TABLE public."attendance" ENABLE ROW LEVEL SECURITY;
ALTER TABLE public."attendance_history" ENABLE ROW LEVEL SECURITY;
ALTER TABLE public."enrollments" ENABLE ROW LEVEL SECURITY;
ALTER TABLE public."report_deliveries" ENABLE ROW LEVEL SECURITY;
ALTER TABLE public."timetable_lessons" ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.alembic_version ENABLE ROW LEVEL SECURITY;

CREATE TABLE public.api_rate_limits (bucket text PRIMARY KEY, expires_at timestamptz NOT NULL, hits integer NOT NULL);
CREATE TABLE public.download_tickets (key_hash text PRIMARY KEY, owner_id integer NOT NULL REFERENCES public.users(id), expires_at timestamptz NOT NULL, payload jsonb NOT NULL);
CREATE TABLE public.telegram_updates (update_id bigint PRIMARY KEY, received_at timestamptz NOT NULL DEFAULT now(), completed_at timestamptz, status text NOT NULL DEFAULT 'processing');
ALTER TABLE public.api_rate_limits ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.download_tickets ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.telegram_updates ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM anon, authenticated;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM anon, authenticated;
GRANT ALL ON ALL TABLES IN SCHEMA public TO service_role;
GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO service_role;
