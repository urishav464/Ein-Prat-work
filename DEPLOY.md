# פריסה — איך מעלים את האפליקציה לחניכים

> המטרה: 10 חניכים נכנסים מהטלפון, כל אחד רואה רק את המשמרים שלו, ואתה רואה הכל.

## מקומית (פיתוח)

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

> ⚠️ **על Streamlit Community Cloud הדיסק זמני.** `mishmar.db` יימחק בכל
> redeploy או הפעלה מחדש של הקונטיינר, ואיתו המשימות, התקציב, המשוב והשיחות.
> לשימוש אמיתי לאורך שנה צריך אחסון מתמיד — למשל Postgres מנוהל, או הרצה על
> שרת עם דיסק קבוע. **זה הפער הפתוח הגדול ביותר בפריסה, ואין לו פתרון בקוד
> כרגע.**

## פרטיות

כל שדות ה-`contact` במאגר המרצים הם `TBD` כרגע, ולכן אין עדיין מידע אישי רגיש.
**לפני שממלאים טלפונים ומיילים של מרצים — ודאו שההתחברות דרך Google פעילה.**
