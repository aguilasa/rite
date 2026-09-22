## Discrepancy sweep

Once per item, before its work commit: `rite sweep --terms <a,b,c> --id <ID> --json`, the terms being
what you changed — renamed symbols, files, flags, config keys, numbers you re-measured.

Fix every stale mention this item owns. One owned by another pending item goes as a note in *that*
item's Notes, not only in your report: a follow-up living in a transcript is lost. Report what you
searched and updated, or `sweep: none`.
