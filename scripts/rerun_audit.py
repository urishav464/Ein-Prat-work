#!/usr/bin/env python3
"""What does each click in app.py cost? — the speed checker.

A Streamlit click costs one of four things, and the source does not say which
unless you trace it:

  callback   `on_click=` / `on_change=`   one run, the write lands before render
  fragment   `if button:` reached only from a `@st.fragment` root  → that fragment reruns
  page       `if button:` at page level  → the whole page reruns
  rerun      `write(); st.rerun()`      → the page runs TWICE (only legitimate right
                                          after a form_submit_button, which already reran,
                                          or to close a dialog)
  bare       a widget with no callback outside a form → changing it reruns its scope
             (the sidebar nav radio is one; at page scope it is a whole-app run)

A static map, not the territory: runtime causes (a value set by code, the cache
TTL, a reconnect) need scripts/harness/ — the trace names the line of each run.

Prints one row per site and exits 1 if any `rerun` outside a form/dialog/nav
exists (a double run); `page` sites are listed for review — a regression fails loudly, like the hook. stdlib only.
Usage: python3 scripts/rerun_audit.py [app.py] [--json]
"""
import ast, json, sys
from pathlib import Path

SRC = Path(sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("--") else "app.py")
AS_JSON = "--json" in sys.argv
BUTTON_ATTRS = {"button", "form_submit_button"}
# every widget that can cause a run; radio (the sidebar nav), text_area and
# file_uploader were missing, so the nav — the commonest app run — was invisible
WIDGET_ATTRS = BUTTON_ATTRS | {"selectbox", "checkbox", "number_input", "text_input",
                               "feedback", "segmented_control", "pills", "toggle",
                               "radio", "text_area", "file_uploader", "multiselect",
                               "date_input", "time_input", "slider", "download_button"}


def _kwarg(call, name):
    return next((k.value for k in call.keywords if k.arg == name), None)


def _label(call):
    if call.args and isinstance(call.args[0], ast.Constant):
        return str(call.args[0].value)[:28]
    if call.args and isinstance(call.args[0], ast.JoinedStr):
        return "".join(v.value for v in call.args[0].values if isinstance(v, ast.Constant))[:28]
    return "?"


class Site:
    def __init__(self, line, label, kind, scope, note=""):
        self.line, self.label, self.kind, self.scope, self.note = line, label, kind, scope, note

    def row(self):
        return {"line": self.line, "label": self.label, "kind": self.kind,
                "scope": self.scope, "note": self.note}


def main():
    tree = ast.parse(SRC.read_text(encoding="utf-8"))
    funcs = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}

    # decorators: fragments and dialogs are roots of their own scope
    def deco_names(fn):
        out = set()
        for d in fn.decorator_list:
            t = d.func if isinstance(d, ast.Call) else d
            if isinstance(t, ast.Attribute):
                out.add(t.attr)
        return out
    fragments = {n for n, f in funcs.items() if "fragment" in deco_names(f)}
    dialogs = {n for n, f in funcs.items() if "dialog" in deco_names(f)}

    # call graph: which module-level functions does each function call?
    calls = {}
    for name, fn in funcs.items():
        out = set()
        for node in ast.walk(fn):
            if isinstance(node, ast.Call):
                t = node.func
                if isinstance(t, ast.Name) and t.id in funcs:
                    out.add(t.id)
            # on_click=_fn / args passed as callables
            if isinstance(node, ast.Name) and node.id in funcs:
                out.add(node.id)
        calls[name] = out

    def reachable_from(roots):
        seen, stack = set(), list(roots)
        while stack:
            n = stack.pop()
            if n in seen:
                continue
            seen.add(n)
            stack.extend(calls.get(n, ()))
        return seen
    in_fragment = reachable_from(fragments)
    in_dialog = reachable_from(dialogs)

    # which top-level functions are reached from main()/show_* only (page scope)
    def scope_of(fname):
        if fname in dialogs or (fname in in_dialog and fname not in in_fragment):
            return "dialog"
        if fname in fragments or fname in in_fragment:
            return "fragment"
        return "page"

    NAV_CALLS = {"_goto", "logout", "_apply_goto", "_login", "_set_nav"}

    def calls_in(node):
        out = set()
        for n in ast.walk(node):
            if isinstance(n, ast.Call):
                t = n.func
                if isinstance(t, ast.Name):
                    out.add(t.id)
                elif isinstance(t, ast.Attribute):
                    out.add(t.attr)
        return out

    sites = []
    for fname, fn in funcs.items():
        scope = scope_of(fname)
        # names bound to a form submit / button result: `saved = c1.form_submit_button(...)`
        submit_names, button_names = set(), set()
        for n in ast.walk(fn):
            if isinstance(n, ast.Assign) and isinstance(n.value, ast.Call) \
                    and isinstance(n.value.func, ast.Attribute):
                names = {t.id for t in n.targets if isinstance(t, ast.Name)}
                if n.value.func.attr == "form_submit_button":
                    submit_names |= names
                elif n.value.func.attr == "button":
                    button_names |= names
        # the `if` a node sits under, innermost first
        parents = {}
        for n in ast.walk(fn):
            for c in ast.iter_child_nodes(n):
                parents[c] = n

        def enclosing_ifs(n):
            while n in parents:
                n = parents[n]
                if isinstance(n, ast.If):
                    yield n

        def in_form(n):
            """Inside `with <x>.form(...)`: no run until the submit."""
            while n in parents:
                n = parents[n]
                if isinstance(n, ast.With) and any(
                        isinstance(i.context_expr, ast.Call)
                        and isinstance(i.context_expr.func, ast.Attribute)
                        and i.context_expr.func.attr == "form" for i in n.items):
                    return True
            return False

        def test_names(t):
            return {x.id for x in ast.walk(t) if isinstance(x, ast.Name)}

        def test_calls(t):
            return {x.func.attr for x in ast.walk(t)
                    if isinstance(x, ast.Call) and isinstance(x.func, ast.Attribute)}

        for node in ast.walk(fn):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                    and node.func.attr in WIDGET_ATTRS:
                attr = node.func.attr
                if _kwarg(node, "on_click") is not None or _kwarg(node, "on_change") is not None:
                    sites.append(Site(node.lineno, _label(node), "callback", scope, attr))
                elif attr == "form_submit_button":
                    sites.append(Site(node.lineno, _label(node), "form-submit", scope, attr))
                elif attr not in BUTTON_ATTRS and not in_form(node):
                    # no callback, not inside a form: changing its value reruns
                    # the scope on its own (the sidebar nav is exactly this)
                    sites.append(Site(node.lineno, _label(node), "bare", scope, attr))
                elif attr == "button":
                    # `if st.button(...)`: what does the body do? navigation and
                    # opening a dialog are reruns by nature — not a regression.
                    owner = next((i for i in enclosing_ifs(node) if node in ast.walk(i.test)), None)
                    body_calls = calls_in(ast.Module(body=owner.body, type_ignores=[])) if owner else set()
                    if body_calls & NAV_CALLS:
                        sites.append(Site(node.lineno, _label(node), "nav", scope, "opens a screen"))
                    elif body_calls & dialogs:
                        sites.append(Site(node.lineno, _label(node), "nav", scope, "opens a dialog"))
                    else:
                        sites.append(Site(node.lineno, _label(node), scope, scope, attr))
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                    and node.func.attr == "rerun" and isinstance(node.func.value, ast.Name) \
                    and node.func.value.id == "st":
                s = Site(node.lineno, "st.rerun", "rerun", scope, "")
                ifs = list(enclosing_ifs(node))
                under_submit = any(test_names(i.test) & submit_names
                                   or "form_submit_button" in test_calls(i.test) for i in ifs)
                # the double run is specifically: a click's `if` body writes, then reruns.
                click_ifs = [i for i in ifs if test_names(i.test) & button_names
                             or "button" in test_calls(i.test)]
                if scope == "dialog":
                    s.note = "closes a dialog"
                elif under_submit:
                    s.note = "after form submit (already reran once)"
                elif click_ifs:
                    body_calls = set().union(*(calls_in(ast.Module(body=i.body, type_ignores=[]))
                                               for i in click_ifs))
                    s.note = ("navigation / auth" if body_calls & NAV_CALLS
                              else "DOUBLE RUN — convert to on_click or fragment")
                else:
                    # not under any click: a state transition at page level
                    # (login resolved, a deep link applied) — the rerun IS the mechanism
                    s.note = "state transition (not click-driven)"
                sites.append(s)

    # `page` is a cost NOTE (a callback outside a fragment reruns the page too);
    # the regression is the double run — write, then st.rerun() — which pays twice.
    bad = [s for s in sites if s.kind == "rerun" and s.note.startswith("DOUBLE")]
    review = [s for s in sites if s.kind == "page"]
    sites.sort(key=lambda s: s.line)
    if AS_JSON:
        counts = {}
        for s in sites:
            counts[s.kind] = counts.get(s.kind, 0) + 1
        print(json.dumps({"file": str(SRC), "fragments": sorted(fragments),
                          "dialogs": sorted(dialogs), "counts": counts,
                          "sites": [s.row() for s in sites],
                          "regressions": [s.row() for s in bad],
                          "review": [s.row() for s in review]}, ensure_ascii=False, indent=1))
    else:
        print(f"{SRC}: fragments={sorted(fragments)} dialogs={sorted(dialogs)}")
        print(f"{'line':>5}  {'kind':<11} {'scope':<8} label / note")
        for s in sites:
            flag = "  <<<" if s in bad else ""
            print(f"{s.line:>5}  {s.kind:<11} {s.scope:<8} {s.label}  {s.note}{flag}")
        counts = {}
        for s in sites:
            counts[s.kind] = counts.get(s.kind, 0) + 1
        print("counts:", counts, "| regressions (double run):", len(bad),
              "| page-level `if button` to review:", [r.line for r in review])
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
