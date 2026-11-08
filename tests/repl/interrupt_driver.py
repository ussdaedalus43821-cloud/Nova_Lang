"""Run the real REPL with scripted input, including Ctrl-C.

    python interrupt_driver.py STEPS_JSON FLAGS_JSON

STEPS_JSON is a list. A string is a line typed at the prompt; "^C" is Ctrl-C
at the prompt (a KeyboardInterrupt out of input()); ["interrupt", LINE] types
LINE and, one second later, delivers a KeyboardInterrupt to the main thread
the way a Ctrl-C press does (_thread.interrupt_main), so a runaway program is
stopped from outside. Running out of steps is end of input. The prompt is
written for every read, as a terminal would show it; typed lines are not
echoed, matching the piped-stdin sessions beside this file.

Piped stdin cannot send Ctrl-C, and a real signal is not portable to Windows;
this reaches the same exception through the same code in the REPL.
"""

import _thread
import builtins
import json
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import novalang  # noqa: E402

steps = json.loads(sys.argv[1])
flags = json.loads(sys.argv[2])


def scripted_input(prompt=""):
    sys.stdout.write(prompt)
    sys.stdout.flush()
    if not steps:
        raise EOFError
    step = steps.pop(0)
    if step == "^C":
        raise KeyboardInterrupt
    if isinstance(step, list):
        timer = threading.Timer(1.0, _thread.interrupt_main)
        timer.daemon = True
        timer.start()
        return step[1]
    return step


builtins.input = scripted_input
sys.exit(novalang.main(["novalang.py"] + flags))
