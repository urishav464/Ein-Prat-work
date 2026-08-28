# פריסה — איך מעלים את האפליקציה לחניכים

> המטרה: 10 חניכים נכנסים מהטלפון, כל אחד רואה רק את המשמרים שלו, ואתה רואה הכל.

> **אין מסד נתונים מקומי ואין קובץ `.env`.** הנתונים יושבים ב-Supabase,
> והמפתחות ב-Streamlit Secrets. זה מה שפותר את בעיית הדיסק הזמני: הקונטיינר
> של Streamlit נמחק בכל redeploy, המסד לא.

## סדר ההקמה — שלושה שלבים

### 1. Supabase — פעם אחת

1. פותחים פרויקט ב-supabase.com.
2. **SQL Editor → New query → מדביקים את כל `supabase_schema.sql` → Run.**
   זה יוצר 12 טבלאות ו-6 תצוגות. אפשר להריץ שוב בבטחה.
   *(ה-REST API לא יכול ליצור טבלאות — לכן השלב הזה ידני ואי אפשר לדלג עליו.)*
3. Project Settings → API → מעתיקים את **URL** ואת מפתח **service_role**.

> ⚠️ **חייב להיות service_role, לא anon.** הסכימה מפעילה RLS על כל הטבלאות בלי
> אף מדיניות: `anon` ו-`authenticated` מקבלים אפס גישה, ו-`service_role` עובר
> מעליהם. זו הסיבה שמפתח ה-anon הציבורי לא פותח כלום — וגם הסיבה שאם תדביקו
> אותו בטעות, האפליקציה תגיד לכם בדיוק את זה במסך הכניסה.

### 2. Streamlit Secrets

Settings → Secrets, ומדביקים לפי `.streamlit/secrets.toml.example`:
`SUPABASE_URL`, `SUPABASE_KEY`, `ANTHROPIC_API_KEY`, `admin_emails`, ובלוק `[auth]`.

**הזריעה אוטומטית.** בהרצה הראשונה האפליקציה קוראת את `students_tasks.md` ואת
מאגר המרצים ומעלה אותם ל-Supabase — 21 משמרים, 10 חניכים, 213 משימות, 46 מרצים.
מוגן בדגל ב-`app_meta`, ולכן לא יקרה פעמיים. **בשונה מהגרסה הקודמת, הקובץ לא
נגנז** — הצ'קאאוט נבנה מחדש מגיט בכל פריסה, אז שינוי שם שם לא היה שורד ממילא.

אם משהו חסר, מסך הכניסה יגיד בדיוק מה — לא ייפתח ריק.

### 3. הרצה מקומית (רשות)

מושכת את אותם נתונים מ-Supabase — אין עותק מקומי.

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

> **התקינו בתוך venv.** `Authlib` (להתחברות Google) מושך את `cryptography`, ועל
> פייתון מערכתי של Debian/Ubuntu זה נופל עם
> *"Cannot uninstall cryptography, RECORD file not found"* — מה שמפיל את כל
> `pip install`, ובשרשרת `&&` גם מונע מ-`streamlit run` לרוץ. venv פותר את זה.
> בלי venv: `pip install --ignore-installed cryptography Authlib`.
> כל האפליקציה חוץ מהתחברות Google עובדת גם בלי Authlib.

בלי `.streamlit/secrets.toml` האפליקציה עולה במצב פיתוח: הזדהות בשם בלבד, בלי סיסמה.
זה בסדר על המחשב שלך, ו**לא** בסדר בכתובת ציבורית.

## הצ'אט

הצ'אט צריך מפתח API. בלעדיו כל השאר עובד והצ'אט מציג הודעה מסודרת.

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
```

או ב-`.streamlit/secrets.toml`. המודל הוא `claude-sonnet-5` — מוגדר ב-`chat_agent.py:MODEL`.

## פריסה ל-Streamlit Community Cloud

**1. דחפו ל-GitHub** (הריפו כבר מוכן; `.streamlit/secrets.toml` ו-`*.db` ב-gitignore).

**2. צרו את האפליקציה** ב-share.streamlit.io מול `app.py` בברנץ׳ הזה.

**3. Google OAuth** — ב-Google Cloud Console → APIs & Services → Credentials →
Create OAuth client ID → Web application. תחת *Authorized redirect URIs* הוסיפו:

```
https://<שם-האפליקציה>.streamlit.app/oauth2callback
```

**4. Secrets** — ב-Settings → Secrets של האפליקציה, הדביקו את התוכן של
`.streamlit/secrets.toml.example` אחרי מילוי. `redirect_uri` חייב להיות זהה
לזה שרשמתם בגוגל, אחרת ההתחברות תיכשל בלי הסבר.

**5. שיוך חשבונות** — היכנסו כמדריך, ובלוח הבקרה תחת «שיוך חשבונות» שייכו
כתובת גוגל לכל חניך. **חניך בלי שיוך יתחבר בהצלחה ולא יראה שום משמר** — זו
ההתנהגות הנכונה, אבל היא מבלבלת אם לא יודעים.

## שני דברים שחייבים לקרות לפני שהחניכים נכנסים

**שמות אמיתיים.** כרגע `חניך 1`–`חניך 10`. ההחלפה היא במסד:

```python
import data_manager as dm
with dm.get_connection() as c:
    c.execute("UPDATE Students SET name=? WHERE name=?", ("שם אמיתי", "חניך 1"))
```

השמות מופיעים גם ב-`Mishmer-section/2026-27/schedule.md` וב-`students.md` — שווה לעדכן שם במקביל.

**המסד נבנה בהרצה הראשונה.** ההרצה הראשונה של `streamlit run app.py` יוצרת את
`mishmar.db`, מייבאת את 193 המשימות מ-`students_tasks.md`, ואז **משנה את שמו**
ל-`students_tasks_ARCHIVED.md`. זו פעולה חד-פעמית ומוגנת בדגל, אבל היא קורית
בהרצה הראשונה — הריצו אותה פעם אחת מקומית ובדקו שהכל נראה נכון לפני הפריסה.

## אבטחה — למה RLS מופעל

הלינטר של Supabase סימן 18 התראות CRITICAL על הגרסה הראשונה, והוא צדק. השארתי
RLS כבוי בהנחה שהמפתח נשאר פרטי — **הנחה שגויה**, כי מפתח ה-anon של Supabase
מיועד להיות ציבורי. בלי RLS כל טבלה ב-`public` פתוחה לכל מי שמחזיק אותו.

התיקון: RLS על כל 12 הטבלאות **בלי אף מדיניות**, ו-`security_invoker` על כל
6 התצוגות כדי שיכבדו את ההרשאות של הקורא ולא של היוצר.

נבדק מול Postgres אמיתי עם תפקידים שמחקים את Supabase:

| תפקיד | תוצאה |
|---|---|
| `anon` (המפתח הציבורי) | `permission denied` על כל טבלה ותצוגה, קריאה וכתיבה |
| `service_role` (האפליקציה) | גישה מלאה |

> ✅ **בעיית הדיסק הזמני נפתרה.** הנתונים ב-Supabase, מחוץ לקונטיינר, ולכן
> משימות, תקציב, משוב ושיחות שורדים redeploy.

## פרטיות

כל שדות ה-`contact` במאגר המרצים הם `TBD` כרגע, ולכן אין עדיין מידע אישי רגיש.
**לפני שממלאים טלפונים ומיילים של מרצים — ודאו שההתחברות דרך Google פעילה.**
