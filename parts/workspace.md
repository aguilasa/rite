## Workspace

If `rite begin` reported `"workspace": false`, ignore this section.

`rite.toml` sits in a plain folder whose sub-folders are the git repositories, and every item names one
in `repo:`. Run its commands and its git inside that folder (`git -C <repo> …`), never at the root, and
read its paths relative to it. One item, one repository. Every cycle there is local: its documents stay
in the workspace folder and are never staged into a repository.
