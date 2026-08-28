-- ===========================================================================
-- supabase_schema.sql — מריצים פעם אחת ב-Supabase SQL Editor
--
-- למה קובץ נפרד: ה-REST API של Supabase לא יכול ליצור טבלאות. הוא קורא וכותב
-- שורות בלבד. לכן כל המבנה יושב כאן, והפייתון רק משתמש בו.
--
-- **איך מריצים:** Supabase → פרויקט → SQL Editor → New query → מדביקים את כל
-- הקובץ → Run. אפשר להריץ שוב; הכל IF NOT EXISTS / OR REPLACE.
--
-- שמות בעברית נשמרים כערכים, לא כשמות עמודות. שמות טבלאות באותיות קטנות —
-- ככה Postgres עובד וככה PostgREST מצפה לראות אותם.
-- ===========================================================================

-- ---------------------------------------------------------------------------
-- 1. הליבה
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS mishmarim (
    id              integer PRIMARY KEY,          -- 1..21, תואם למספר התיקייה
    gregorian_date  text NOT NULL,                -- '24.9.2026'
    hebrew_date     text NOT NULL,                -- 'י״ג תשרי תשפ״ז'
    mishmar_type    text,                         -- 'פנימי' / 'חיצוני'
    topic           text,                         -- NULL = טרם נסגר. אף פעם לא ניחוש.
    note            text,
    workfile_path   text,
    is_staff_built  boolean NOT NULL DEFAULT false
);

CREATE TABLE IF NOT EXISTS students (
    id     integer PRIMARY KEY,
    name   text NOT NULL UNIQUE,
    role   text NOT NULL DEFAULT 'student',
    email  text                                    -- לשיוך חשבון Google
);

-- בעלות על משמר היא של **זוג**, ולכן רבים-לרבים.
CREATE TABLE IF NOT EXISTS assignments (
    mishmar_id  integer NOT NULL REFERENCES mishmarim(id) ON DELETE CASCADE,
    student_id  integer NOT NULL REFERENCES students(id)  ON DELETE CASCADE,
    PRIMARY KEY (mishmar_id, student_id)
);

CREATE TABLE IF NOT EXISTS tasks (
    id                bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    mishmar_id        integer NOT NULL REFERENCES mishmarim(id) ON DELETE CASCADE,
    -- NULL = המשימה שייכת למשמר, כלומר לשני בני הזוג.
    student_id        integer REFERENCES students(id) ON DELETE SET NULL,
    task_description  text NOT NULL,
    status            text NOT NULL DEFAULT 'TO DO'
                      CHECK (status IN ('TO DO', 'IN PROGRESS', 'DONE')),
    category          text,
    due_date          date,                        -- נגזר, לא מוקלד
    created_at        timestamptz NOT NULL DEFAULT now(),
    updated_at        timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS budget (
    id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    mishmar_id   integer NOT NULL REFERENCES mishmarim(id) ON DELETE CASCADE,
    expense_type text NOT NULL,                    -- 'מרצה' / 'כיבוד' / 'אחר'
    description  text,
    amount       numeric DEFAULT 0,
    actual_cost  numeric DEFAULT 0,                -- 0 = הגיע בהתנדבות
    created_at   timestamptz NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- 2. מרצים
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS speakers (
    id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    -- שם בלבד. **תואר אינו חלק מהשם** — ד״ר, פרופ׳ והרב יושבים ב-title.
    name             text NOT NULL,
    title            text,
    -- גרשיים עבריים מקופלים ל-ASCII, כעמודה מחושבת. חייב להיות כאן ולא בפייתון:
    -- ה-REST API לא יודע להריץ REPLACE בתוך תנאי סינון, ובלי זה חניך שמקליד
    -- ד"ר לא מוצא את ד״ר — ואז נוצרת רשומה כפולה לאותו אדם.
    name_norm        text GENERATED ALWAYS AS (
                         replace(replace(name, '״', '"'), '׳', '''')
                     ) STORED,
    expertise_topics text,
    verification_url text,
    source_type      text NOT NULL DEFAULT 'manual'
                     CHECK (source_type IN ('original_44','web_search','manual')),
    -- הסטטוס ההיסטורי מהמאגר חוצה-השנים. הסטטוס **הנוכחי** נגזר מיומן
    -- הפניות ב-v_speaker_status, ולא נשמר כאן.
    status           text DEFAULT '⬜ לא פנינו',
    lesson_fit       text,
    region           text,
    contact          text,                         -- TBD עד שאדם ממלא. אף פעם לא נגרד מהרשת.
    notes            text,
    created_at       timestamptz NOT NULL DEFAULT now(),
    UNIQUE (name, source_type)
);

-- פנייה היא **יומן, לא שדה**. לפני זה סגירת מרצה נכתבה רק ליד המשמר הבודד,
-- והמאגר המשותף אף פעם לא למד — מה שביטל בדיוק את המנגנון שאמור למנוע משני
-- זוגות לפנות לאותו אדם בלי לדעת.
CREATE TABLE IF NOT EXISTS speaker_outreach (
    id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    speaker_id bigint  NOT NULL REFERENCES speakers(id)  ON DELETE CASCADE,
    mishmar_id integer REFERENCES mishmarim(id) ON DELETE SET NULL,
    student_id integer REFERENCES students(id)  ON DELETE SET NULL,
    status     text NOT NULL,
    note       text,
    created_at timestamptz NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- 3. הערב עצמו
-- ---------------------------------------------------------------------------

-- **בכוונה לא ארבע שורות קבועות.** בארכיון 2025-26 יש ערב עם טקס ושני שיעורים,
-- ויש מעגל שירה. ארבעת השיעורים הם ברירת מחדל, לא אילוץ של מבנה הנתונים.
CREATE TABLE IF NOT EXISTS lessons (
    id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    mishmar_id     integer NOT NULL REFERENCES mishmarim(id) ON DELETE CASCADE,
    slot_order     integer NOT NULL,
    start_time     text,
    title          text,
    description    text,
    lesson_role    text,
    speaker_name   text,
    speaker_status text DEFAULT '⬜ לא פנינו',      -- מראה של היומן, לא מקור עצמאי
    format         text,
    created_at     timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS feedback (
    id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    mishmar_id   integer NOT NULL REFERENCES mishmarim(id) ON DELETE CASCADE,
    student_id   integer REFERENCES students(id) ON DELETE SET NULL,
    lesson_id    bigint  REFERENCES lessons(id)  ON DELETE SET NULL,
    speaker_name text,
    rating       integer CHECK (rating BETWEEN 1 AND 5),
    what_worked  text,
    what_didnt   text,
    created_at   timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS chat_messages (
    id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    mishmar_id integer REFERENCES mishmarim(id) ON DELETE CASCADE,
    student_id integer REFERENCES students(id)  ON DELETE SET NULL,
    role       text NOT NULL CHECK (role IN ('user','assistant')),
    content    text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

-- מטמון חיפוש. כל החניכים מאחורי IP אחד, ולכן שאילתה שכבר רצה חייבת לעלות
-- קריאת רשת אחת ולא עשר.
CREATE TABLE IF NOT EXISTS search_cache (
    query_hash   text PRIMARY KEY,
    query_text   text NOT NULL,
    results_json jsonb NOT NULL,
    -- false = הקריאה נכשלה או חזרה ריקה. נשמר גם, אבל לשעה ולא לחודשיים,
    -- אחרת אחר צהריים אחד של חסימה מרעיל את המטמון לכל העונה.
    ok           boolean NOT NULL DEFAULT true,
    created_at   timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS app_meta (
    key   text PRIMARY KEY,
    value text
);

-- ---------------------------------------------------------------------------
-- 4. אינדקסים
-- ---------------------------------------------------------------------------

CREATE INDEX IF NOT EXISTS idx_tasks_mishmar     ON tasks(mishmar_id);
CREATE INDEX IF NOT EXISTS idx_tasks_status      ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_due         ON tasks(due_date);
CREATE INDEX IF NOT EXISTS idx_budget_mishmar    ON budget(mishmar_id);
CREATE INDEX IF NOT EXISTS idx_speakers_src      ON speakers(source_type);
CREATE INDEX IF NOT EXISTS idx_speakers_norm     ON speakers(name_norm);
CREATE INDEX IF NOT EXISTS idx_outreach_speaker  ON speaker_outreach(speaker_id, id);
CREATE INDEX IF NOT EXISTS idx_outreach_mishmar  ON speaker_outreach(mishmar_id);
CREATE INDEX IF NOT EXISTS idx_lessons_mishmar   ON lessons(mishmar_id);
CREATE INDEX IF NOT EXISTS idx_feedback_mishmar  ON feedback(mishmar_id);
CREATE INDEX IF NOT EXISTS idx_chat_lookup       ON chat_messages(mishmar_id, student_id, id);
CREATE INDEX IF NOT EXISTS idx_cache_created     ON search_cache(created_at);

-- ---------------------------------------------------------------------------
-- 5. תצוגות
--
-- PostgREST לא יודע לבטא צירופים ואגרגציות מורכבות, ולכן כל מה שדורש JOIN או
-- GROUP BY יושב כאן, ו-Python רק קורא תצוגה. זה גם הופך את הנתונים הנגזרים
-- לבלתי-ניתנים-לסטייה: אין עותק שמור שיכול להתיישן.
-- ---------------------------------------------------------------------------

-- הוצאות בפועל למשמר. אף פעם לא עמודה שמורה.
CREATE OR REPLACE VIEW v_mishmar_budget
WITH (security_invoker = true) AS
SELECT m.id                              AS mishmar_id,
       m.gregorian_date,
       COALESCE(SUM(b.actual_cost), 0)   AS budget_used
  FROM mishmarim m
  LEFT JOIN budget b ON b.mishmar_id = m.id
 GROUP BY m.id, m.gregorian_date;

-- הסטטוס הנוכחי של מרצה = השורה האחרונה ביומן הפניות, ובהיעדרה הערך ההיסטורי.
CREATE OR REPLACE VIEW v_speaker_status
WITH (security_invoker = true) AS
SELECT s.id                                AS speaker_id,
       s.name,
       s.name_norm,
       s.title,
       s.expertise_topics,
       s.lesson_fit,
       s.region,
       s.contact,
       s.notes,
       s.source_type,
       COALESCE(o.status, s.status)        AS current_status,
       o.mishmar_id                        AS last_mishmar_id,
       o.student_id                        AS last_student_id,
       o.created_at                        AS last_contact_at,
       (o.id IS NOT NULL)                  AS has_outreach
  FROM speakers s
  LEFT JOIN LATERAL (
       SELECT * FROM speaker_outreach
        WHERE speaker_id = s.id
        ORDER BY id DESC
        LIMIT 1
  ) o ON true;

-- יומן הפניות עם השמות מפוענחים — מה שחניך רואה לפני שהוא פונה.
CREATE OR REPLACE VIEW v_outreach_full
WITH (security_invoker = true) AS
SELECT o.id,
       o.speaker_id,
       sp.name        AS speaker_name,
       o.mishmar_id,
       m.gregorian_date,
       m.topic,
       o.student_id,
       st.name        AS student_name,
       o.status,
       o.note,
       o.created_at
  FROM speaker_outreach o
  JOIN speakers  sp ON sp.id = o.speaker_id
  LEFT JOIN mishmarim m  ON m.id  = o.mishmar_id
  LEFT JOIN students  st ON st.id = o.student_id;

-- משימות עם פרטי המשמר, לקנבן ולהקשר של הצ'אט.
CREATE OR REPLACE VIEW v_tasks_full
WITH (security_invoker = true) AS
SELECT t.*,
       m.gregorian_date,
       m.hebrew_date,
       m.topic
  FROM tasks t
  JOIN mishmarim m ON m.id = t.mishmar_id;

-- משימות פתוחות שעברו את התאריך המומלץ, עם הזוג האחראי.
-- #01 ו-#02 נבנים על ידי הצוות ואין להם שורות ב-assignments — לכן COALESCE,
-- אחרת השדה חוזר NULL וכל מי שמעצב אותו נופל.
CREATE OR REPLACE VIEW v_overdue_tasks
WITH (security_invoker = true) AS
SELECT t.*,
       m.gregorian_date,
       m.hebrew_date,
       m.topic,
       COALESCE((SELECT string_agg(s.name, ' + ' ORDER BY s.name)
                   FROM assignments a JOIN students s ON s.id = a.student_id
                  WHERE a.mishmar_id = m.id), 'צוות') AS owners
  FROM tasks t
  JOIN mishmarim m ON m.id = t.mishmar_id
 WHERE t.status <> 'DONE'
   AND t.due_date IS NOT NULL
   AND t.due_date < CURRENT_DATE;

-- התקדמות לכל חניך. משימות של חניך = משימות המשמרים שלו, כולל המשותפות.
CREATE OR REPLACE VIEW v_student_progress
WITH (security_invoker = true) AS
SELECT s.id,
       s.name,
       COUNT(DISTINCT a.mishmar_id)                                   AS mishmarim,
       COUNT(t.id)                                                    AS tasks_total,
       COUNT(t.id) FILTER (WHERE t.status = 'DONE')                   AS tasks_done,
       COUNT(t.id) FILTER (WHERE t.status <> 'DONE'
                             AND t.due_date IS NOT NULL
                             AND t.due_date < CURRENT_DATE)           AS overdue
  FROM students s
  LEFT JOIN assignments a ON a.student_id = s.id
  LEFT JOIN tasks t ON t.mishmar_id = a.mishmar_id
                   AND (t.student_id IS NULL OR t.student_id = s.id)
 WHERE s.role = 'student'
 GROUP BY s.id, s.name;

-- ---------------------------------------------------------------------------
-- 6. הרשאות — RLS על כל טבלה, בלי אף מדיניות
--
-- **תיקון להחלטה קודמת.** קודם השארתי RLS כבוי בהנחה שהמפתח נשאר פרטי
-- ב-Streamlit Secrets. ההנחה הזו שגויה: מפתח ה-anon של Supabase מיועד להיות
-- ציבורי מעצם תכנונו. בלי RLS, כל טבלה ב-public פתוחה לקריאה ולכתיבה לכל מי
-- שמחזיק אותו — לא משנה מה האפליקציה עושה. זה מה שהלינטר סימן, והוא צדק.
--
-- מפעילים RLS **בלי להוסיף מדיניות**, וזה בדיוק הנכון לארכיטקטורה הזו:
--
--   * `anon` / `authenticated`  → אפס גישה. אין מדיניות, אין הרשאה.
--   * `service_role`            → גישה מלאה; לתפקיד הזה יש BYPASSRLS.
--
-- ⚠️ **לכן `SUPABASE_KEY` ב-Streamlit חייב להיות מפתח ה-service_role.**
-- אם הוכנס שם מפתח anon, האפליקציה תראה מסד ריק אחרי ההרצה הזו.
-- Supabase → Project Settings → API → service_role (מסומן secret).
--
-- זה עדיין מפתח שמעניק הכל למי שמחזיק בו — הוא נשאר רק ב-Streamlit Secrets,
-- לעולם לא בגיט. אבל מפתח ה-anon הציבורי כבר לא פותח שום דבר.
-- ---------------------------------------------------------------------------

ALTER TABLE mishmarim        ENABLE ROW LEVEL SECURITY;
ALTER TABLE students         ENABLE ROW LEVEL SECURITY;
ALTER TABLE assignments      ENABLE ROW LEVEL SECURITY;
ALTER TABLE tasks            ENABLE ROW LEVEL SECURITY;
ALTER TABLE budget           ENABLE ROW LEVEL SECURITY;
ALTER TABLE speakers         ENABLE ROW LEVEL SECURITY;
ALTER TABLE speaker_outreach ENABLE ROW LEVEL SECURITY;
ALTER TABLE lessons          ENABLE ROW LEVEL SECURITY;
ALTER TABLE feedback         ENABLE ROW LEVEL SECURITY;
ALTER TABLE chat_messages    ENABLE ROW LEVEL SECURITY;
ALTER TABLE search_cache     ENABLE ROW LEVEL SECURITY;
ALTER TABLE app_meta         ENABLE ROW LEVEL SECURITY;

-- הסרת ההרשאות ש-Supabase מעניק אוטומטית לתפקידים הציבוריים. RLS לבדו מספיק,
-- אבל שתי שכבות עדיפות על אחת, וזה גם מבהיר את הכוונה.
REVOKE ALL ON ALL TABLES    IN SCHEMA public FROM anon, authenticated;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM anon, authenticated;

-- מסמן שהסכימה הותקנה, כדי שהאפליקציה תוכל לומר משהו מועיל אם לא.
INSERT INTO app_meta (key, value)
VALUES ('schema_version', '1')
ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value;
