"""A PostgREST-shaped shim over local PostgreSQL, for driving data_manager
without Supabase. Covers exactly the supabase-py surface data_manager uses:
table().select/insert/upsert/update/delete + eq/neq/in_/is_/ilike/order/limit
+ execute(). Runs every statement under `SET ROLE service_role` so RLS and the
GRANT block are genuinely exercised, and serialises like PostgREST does
(datetime/date -> ISO strings, Decimal -> float) so it is no more forgiving
than production. No `.storage` — uploads fail loudly, as they should here.

Test-only: part of scripts/harness/, never imported by the app. The DSN comes
from MISHMAR_PG_DSN (db.py prints it), so the same file serves any fixture."""
import datetime, decimal, os
import psycopg2, psycopg2.extras

DSN = os.environ.get("MISHMAR_PG_DSN",
                     "host=/tmp port=55432 dbname=mishmar_fixture user=postgres")


def _ser(v):
    if isinstance(v, (datetime.datetime, datetime.date, datetime.time)):
        return v.isoformat()
    if isinstance(v, decimal.Decimal):
        return float(v)
    return v


def _q(ident: str) -> str:
    return '"' + ident.replace('"', '""') + '"'


def _param(v):
    if isinstance(v, (dict, list)):
        return psycopg2.extras.Json(v)
    return v


class Resp:
    def __init__(self, data):
        self.data = data


class Query:
    def __init__(self, table: str):
        self.table = table
        self.verb = None
        self.cols = "*"
        self.payload = None
        self.filters: list = []
        self.orders: list = []
        self._limit = None
        self.on_conflict = None

    # ---- verbs ----
    def select(self, cols="*", count=None):
        self.verb = "select"; self.cols = cols; return self
    def insert(self, rows):
        self.verb = "insert"; self.payload = rows; return self
    def upsert(self, rows, on_conflict=None):
        self.verb = "upsert"; self.payload = rows; self.on_conflict = on_conflict; return self
    def update(self, fields):
        self.verb = "update"; self.payload = fields; return self
    def delete(self):
        self.verb = "delete"; return self

    # ---- filters ----
    def eq(self, c, v):   self.filters.append(("eq", c, v)); return self
    def neq(self, c, v):  self.filters.append(("neq", c, v)); return self
    def in_(self, c, vs): self.filters.append(("in", c, list(vs))); return self
    def is_(self, c, v):  self.filters.append(("is", c, v)); return self
    def ilike(self, c, p): self.filters.append(("ilike", c, p)); return self
    def order(self, c, desc=False): self.orders.append((c, desc)); return self
    def limit(self, n): self._limit = int(n); return self

    # ---- build ----
    def _where(self):
        parts, params = [], []
        for op, c, v in self.filters:
            if op == "eq":
                if v is None:
                    parts.append(f"{_q(c)} IS NULL")
                else:
                    parts.append(f"{_q(c)} = %s"); params.append(_param(v))
            elif op == "neq":
                parts.append(f"{_q(c)} IS DISTINCT FROM %s"); params.append(_param(v))
            elif op == "in":
                if not v:
                    parts.append("FALSE")
                else:
                    parts.append(f"{_q(c)} = ANY(%s)"); params.append(list(v))
            elif op == "is":
                if v is None or str(v).lower() == "null":
                    parts.append(f"{_q(c)} IS NULL")
                elif str(v).lower() in ("true", "false"):
                    parts.append(f"{_q(c)} IS {str(v).upper()}")
                else:
                    parts.append(f"{_q(c)} IS NOT NULL")
            elif op == "ilike":
                parts.append(f"{_q(c)}::text ILIKE %s"); params.append(v)
        return (" WHERE " + " AND ".join(parts)) if parts else "", params

    def _cols_sql(self):
        if self.cols.strip() == "*":
            return "*"
        return ", ".join(_q(c.strip()) for c in self.cols.split(",") if c.strip())

    def _sql(self):
        t = _q(self.table)
        if self.verb == "select":
            where, params = self._where()
            order = (" ORDER BY " + ", ".join(f"{_q(c)} {'DESC' if d else 'ASC'}"
                                              for c, d in self.orders)) if self.orders else ""
            lim = f" LIMIT {self._limit}" if self._limit else ""
            return [(f"SELECT {self._cols_sql()} FROM {t}{where}{order}{lim}", params)]
        if self.verb in ("insert", "upsert"):
            rows = self.payload if isinstance(self.payload, list) else [self.payload]
            stmts = []
            for row in rows:
                cols = list(row.keys())
                sql = (f"INSERT INTO {t} ({', '.join(_q(c) for c in cols)}) VALUES "
                       f"({', '.join(['%s'] * len(cols))})")
                if self.verb == "upsert":
                    target = self.on_conflict or ("id" if "id" in row else None)
                    if target:
                        tcols = ", ".join(_q(c.strip()) for c in target.split(","))
                        sets = ", ".join(f"{_q(c)} = EXCLUDED.{_q(c)}" for c in cols
                                         if c not in [x.strip() for x in target.split(",")])
                        sql += f" ON CONFLICT ({tcols}) DO " + (f"UPDATE SET {sets}" if sets else "NOTHING")
                stmts.append((sql + " RETURNING *", [_param(row[c]) for c in cols]))
            return stmts
        if self.verb == "update":
            where, params = self._where()
            cols = list(self.payload.keys())
            sets = ", ".join(f"{_q(c)} = %s" for c in cols)
            return [(f"UPDATE {t} SET {sets}{where} RETURNING *",
                     [_param(self.payload[c]) for c in cols] + params)]
        if self.verb == "delete":
            where, params = self._where()
            return [(f"DELETE FROM {t}{where} RETURNING *", params)]
        raise ValueError("no verb")

    def execute(self):
        out = []
        conn = psycopg2.connect(DSN)
        try:
            with conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("SET ROLE service_role")
                for sql, params in self._sql():
                    cur.execute(sql, params)
                    if cur.description:
                        out.extend({k: _ser(v) for k, v in dict(r).items()} for r in cur.fetchall())
        finally:
            conn.close()
        return Resp(out)


class FakeSupabase:
    def table(self, name: str) -> Query:
        return Query(name)
    # no `.storage`: upload_* catch the AttributeError and report it
