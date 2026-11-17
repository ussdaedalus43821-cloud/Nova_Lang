# Deprecations

The list of what is deprecated and when it can go; the rules are in [STABLE.md](STABLE.md). A row is added in the
minor release that deprecates the item and removed in the major release that removes it.

| Item | Deprecated in | Replaced by | Earliest removal |
| --- | --- | --- | --- |
| *(nothing is deprecated)* | | | |

How a call of a listed function behaves is [`[host.warnings]`](10-host.md). The list is empty because nothing is deprecated; the mechanism is
tested by a function that is not part of the language ([`[host.probe]`](10-host.md)). The table in `novalang.py` (`DEPRECATED`) and this one are
kept equal by a test.
