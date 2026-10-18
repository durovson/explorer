-- Persist the active language for every user across Render restarts.
ALTER TABLE public.users ADD COLUMN IF NOT EXISTS language text NOT NULL DEFAULT 'ru';
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'public.users'::regclass
          AND conname = 'users_language_check'
    ) THEN
        ALTER TABLE public.users
            ADD CONSTRAINT users_language_check CHECK (language IN ('ru', 'en'));
    END IF;
END;
$$;
