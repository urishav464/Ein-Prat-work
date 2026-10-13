-- «מתנות למרצים אשר הגיעו בחינם» is handed over on the evening itself, not after it.
-- The app's task template and classifier say so from 2026-10-13; this moves the rows an
-- earlier «איפוס משמר» created: category אחרי → יום המשמר, due date → the evening's date
-- (יום המשמר is offset 0). Optional and cosmetic — after an evening the daily auto-close
-- closes the row anyway. Idempotent: a second run matches nothing.
UPDATE tasks t
   SET category   = 'יום המשמר',
       due_date   = to_date(m.gregorian_date, 'DD.MM.YYYY'),
       updated_at = now()
  FROM mishmarim m
 WHERE m.id = t.mishmar_id
   AND t.task_description = 'מתנות למרצים אשר הגיעו בחינם'
   AND t.category = 'אחרי';
