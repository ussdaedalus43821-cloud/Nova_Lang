# Command-line regression tests

```sh
python3 -m unittest discover -s tests/cli -v
python3 tests/run_all.py --station cli
```

The full suite runs this station automatically. Its one parent check wraps 32
unit tests with additional subcases. Successful CLI entry points are exercised
as separate Python processes, not replaced by mocks of their implementations.

Each test uses its own temporary directory. Assertions cover stdout/stderr,
diagnostic locations, exit status, source contents, no-op write timestamps and
absence of unwanted execution. Files with spaces and arguments with quotes and
backslashes are passed as argument arrays without a shell.

The formatter/linter/disassembly tools use status 2 for usage, read and syntax
errors. Lint findings and formatting-check differences use status 1 where
appropriate. A normal lint warning succeeds unless `--strict` is selected.
Bootstrap uses status 1 for source errors, status 2 for missing arguments, and
preserves an explicit script `exit()` status.

Unreadable-input cases use missing paths, directories and invalid UTF-8 bytes;
they do not depend on chmod behaving identically for administrators or on every
operating system. Malformed bytes must not alter formatter inputs, leak a Python
traceback or prevent batch tools from processing later valid files.

Syntax diagnostics are checked against each engine's established contract.
Bootstrap reports its own `ParseError@` format; it does not share the host
parser's exact wording.
