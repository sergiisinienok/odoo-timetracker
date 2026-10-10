# 0015 — Every project is shown by its own Odoo name, not the client's

Status: accepted by owner 2026-10-10, after decision 0014.

## What changes

The picker, the month view, the history list and the catalog label every
project by **its own `project.project.name`, exactly as Odoo shows it**. The
client's name (the project's customer) is no longer used, and neither is the
rule that appended the project name when one client had two projects.

## Why

Showing the client's name was confusing next to Odoo, which lists projects by
name, and it made several engagements for one client hard to tell apart — the
app only disambiguated them when both were in the same employee's list.

## Consequences

- Ops controls what employees read by naming projects in Odoo. Project names
  like "S00001" (Odoo's default for a project made from a sales order) now reach
  employees as they are; rename them in Odoo if they should read better.
- The catalog no longer reads `partner_id`; one Odoo field fewer.
- Entry and catalog labels are now the same string, so the web app uses the
  entry's own `project_label` and no longer looks the label up in the catalog.
- Supersedes the labelling parts of 0011 ("customer name … project name appended")
  and 0014 ("unbillable projects by name, billable by client"). Brief v10.

## Reversibility

Only `label_for` in the catalog service and the brief's wording; the customer
name is still one `partner_id` read away.
