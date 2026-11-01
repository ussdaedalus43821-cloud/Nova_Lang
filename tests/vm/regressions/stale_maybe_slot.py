"""Found by station 11 (generator seed 3975), and present since the VM was
written: a module-level block's assignment to a global that an earlier
input made is decided when it runs - but the block's slot for that name
kept the value a `let` gave it on the previous loop iteration, so the
assignment went to the stale block-local instead of the global. Each
iteration's scope is new; its slots must start empty (RESET_SLOTS).

Run as two inputs to one interpreter, because only a separately compiled
input can make a global the compiler cannot see."""

FIRST = "let a = 0\n"
SECOND = '''for round_number in [1, 2, 3] {
    a = a + 10           # the global, every time
    a = a + 1            # still the global - this is the store that went
                         # wrong: having just been assigned, `a` might be
                         # this block's, so its slot is checked first
    let a = -1           # this iteration's own a, gone when it ends
}
print(a)                 # 33
'''

CHUNKS = [FIRST, SECOND]
EXPECTED = "33\n"
