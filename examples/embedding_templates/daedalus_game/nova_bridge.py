"""nova_bridge.py - same role as reactor_game's: the only pygame-free seam
between Daedalus and NovaLang. See that file's docstring for the general
idea; the one addition here is expose_module(), used to let NovaLang's
python.import("random")-style access reach a module beyond the built-in
allowlist if your logic ever needs one - not used by this template, but
wired through since a real game's logic often eventually wants one
(e.g. a level-data module you want NovaLang scripts to read directly).
"""
import os
import sys

# See reactor_game/nova_bridge.py's comment on this path - vendor
# novalang.py into your own project and adjust this instead.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
from novalang import Nova, NovaLangError  # noqa: E402

NOVA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "nova")


class NovaEngine:
    def __init__(self, scripts):
        self.nova = Nova()
        for script in scripts:
            self.nova.load_file(os.path.join(NOVA_DIR, script))

    def expose(self, name, value):
        self.nova.expose_global(name, value)

    def expose_module(self, module):
        self.nova.expose_module(module)

    def call(self, fn_name, *args):
        try:
            return self.nova.call(fn_name, *args)
        except NovaLangError as error:
            raise RuntimeError("NovaLang error in {}(): {}".format(fn_name, error)) from error
