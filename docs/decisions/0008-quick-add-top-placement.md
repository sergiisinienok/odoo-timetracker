# 0008 — Quick-add form moved to the top, against Appendix F's own mockup

**Discovered:** step 2.5, after the owner's own manual use of the app.

## What Appendix F says

The "Layout: the month is the object" mockup pins the entry form at the
bottom, deliberately:

```
┌──────────────────────────────────┐
│ September                 37.5 h │   month, running total, no chrome
├──────────────────────────────────┤
│ Mon 7   ███████▌           7.5 ▸ │   bar length is the hours
│ ...                               │
└──────────────────────────────────┘
  + Log time                          pinned, thumb-height
```

"Pinned, thumb-height" is a specific mobile-first choice: a bottom sheet is
the part of a phone screen the thumb reaches without repositioning the
hand, and the plan's own "under 60 seconds from a cold load" validate
target for this step assumes fast one-handed entry.

## What happened

The step 2.5 build followed the mockup literally: `.quick-add` was
`position: fixed; bottom: 0`, with `.app` reserving 140px of bottom padding
so page content wouldn't sit underneath it.

Using the built app, the owner found two real problems with that:

1. The fixed panel visually overlapped the "by assignment" list once it
   grew to around five rows — the reserved 140px wasn't enough headroom
   for the form's own content on some viewports, so the assignment list
   was partly hidden behind it rather than scrolling clear.
2. The reserved 140px was permanent dead space at the bottom of every
   screen, whether or not the form actually needed it, on top of the
   day-list rows being uniformly 44px tall even for empty days (a separate
   issue — the disabled expand button was silently forcing that floor
   through every row, contrary to the mockup's own "empty day: a rule,
   and nothing else").

## Changed

Two independent fixes landed together:

- The empty-day row height bug is a straightforward implementation defect
  against the mockup's own stated intent, not a deviation — empty days no
  longer render a button at all, so they no longer force the 44px
  touch-target floor Appendix F never asked for on a row with nothing to
  tap.
- The form's position is a deliberate deviation, not a bug fix: at the
  owner's explicit direction, `.quick-add` moved from a fixed bottom sheet
  to a normal in-flow block directly under the month header, and the
  redundant bottom-fixed locked-notice text was dropped along with it.

Both sections of the page (day list, assignment totals) were also grouped
into `<details>` accordions in the same pass, independently collapsible —
not itself a deviation from Appendix F, which didn't specify this, but
noted here since it landed in the same UI pass.

## Consequence

The documented "pinned, thumb-height" mobile interaction pattern is gone.
Logging a day now requires seeing the top of the page rather than reaching
a fixed bottom bar from anywhere in the scroll — a real trade-off against
one-handed phone use, accepted deliberately in exchange for fixing the
overlap and the wasted screen space. If one-handed thumb reach turns out
to matter in practice (this is exactly the kind of thing Phase 3's pilot
month is for), revisit rather than assume the mockup was simply wrong.

## Re-verify

Nothing Odoo-side — this is a UI decision, not a probed fact. Worth
re-checking against actual one-handed phone use during the Phase 3 pilot,
per the plan's own "collect the things nobody predicted" instruction for
that phase.
