# 0002 — Correcting 0001: `search_read` domains and the `call()` helper convention

**Discovered:** step 0.2, while writing `probe_create_test_lines.py`. The
same underlying mistake also produced the "empty domain raises ValueError"
claim recorded in `0001-odoo19-rpc-quirks.md` — that claim is wrong and is
corrected here.

## What actually happened

`probe_create_test_lines.py` called:

```python
call("hr.employee", "search_read",
     [[("work_email", "=", EMPLOYEE_EMAIL)]],
     fields=["id", "name"])
```

and failed with:

```
ValueError: Domain() invalid item in domain:
  [['work_email', '=', 'polina@particlesglobal.com']]
```

This is the same failure shape as 0001's "empty domain" finding, and for
the same reason: the domain argument was wrapped in one extra list before
being handed to `call()`.

## The actual rule

Given the shared helper used throughout `tools/`:

```python
def call(model, method, *args, **kw):
    return models.execute_kw(DB, uid, KEY, model, method, list(args), kw)
```

Whatever is passed as the **third positional argument to `call()` is
exactly what the target method receives as its first positional
argument** — `list(args)` on the way in adds no extra nesting; it only
turns the tuple `args` into a list, one-for-one. So for
`search_read(domain, fields=...)`, the third argument to `call()` must be
the domain value **itself**, not the domain wrapped in another list:

```python
call(model, "search_read", DOMAIN, fields=[...])
```

where `DOMAIN` is ordinary Odoo domain syntax:

| Intent                | Correct `DOMAIN`                                |
|------------------------|--------------------------------------------------|
| match everything        | `[]`                                            |
| one condition            | `[("field", "=", "value")]`                     |
| two conditions (AND)     | `[("field1", "=", "a"), ("field2", "=", "b")]`  |

Wrapping any of these in an *extra* outer list — `[[]]`,
`[[("field", "=", "value")]]` — produces a domain whose single "condition"
is itself a list, which Odoo correctly rejects. That's what both 0001's
empty-domain finding and this one actually were: not an Odoo 19 behaviour
change, a bracket-counting mistake in how these scripts called the shared
helper.

## Changed

- `probe_create_test_lines.py`'s three `search_read` calls fixed to drop
  the extra wrapping.
- `docs/decisions/0001-odoo19-rpc-quirks.md`'s empty-domain bullet struck
  and pointed here.
- `CLAUDE.md`'s matching "quirk" bullet corrected the same way — the
  suggested `[('id', '>', 0)]` workaround was solving a problem that didn't
  actually exist as described; a genuinely empty `[]` domain works fine
  once it isn't double-wrapped.
- The rest of 0001's findings (`has_group()` faulting, `group_ids` /
  `category_id` renames, `ir.model.data` being access-restricted
  independent of app-level permissions) are unaffected by this correction
  — those were field-name and access-control issues, not domain
  construction, and stand as originally recorded.
