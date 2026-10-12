## Repositories

If `rite begin` gave no `commit.repo_dir`, ignore this section.

An item's work lands in its repository, `commit.repo_dir`: run its commands and git there (`git -C
<repo_dir> …`, a batch's `status` and `stash` too) and read its paths relative to it. One item, one
repository. Rite's documents are never staged there; in a workspace every cycle is local.
