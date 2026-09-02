"""nova_bridge.py - the only file in this template that imports novalang.

Deliberately has no pygame import: this is the seam between your game and
NovaLang, and keeping it pygame-free is what makes it possible to unit-test
your ported game logic (see test_reactor_logic.py) without a display, an
event loop, or any of pygame - the same reason novalang.py itself has zero
dependencies. main.py is the only file that touches both this and pygame.
"""
import os
import sys

# This path climbs from examples/embedding_templates/reactor_game/ back up
# to the NovaLang repo root, purely so this template runs in place for
# testing. In your own project, vendor novalang.py in (it's one file, no
# dependencies) and point this at wherever you put it instead - e.g.
# sys.path.insert(0, os.path.join(os.path.dirname(__file__), "vendor")).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
from novalang import Nova, NovaLangError  # noqa: E402

NOVA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "nova")


class NovaEngine:
    """Thin wrapper around Nova for one game: loads every .nova script
    once at startup, exposes Python objects to it, and turns any
    NovaLangError from a bad script into an ordinary Python exception with
    a message that names which call failed - so a bug in a .nova file
    shows up like any other bug in your traceback, not a silent no-op."""

    def __init__(self, scripts):
        self.nova = Nova()
        for script in scripts:
            self.nova.load_file(os.path.join(NOVA_DIR, script))

    def expose(self, name, value):
        """`value` is a REAL Python object with real methods (a class
        instance) -> NovaLang gets a live, zero-copy proxy: reading/writing
        its fields and calling its methods from NovaLang acts on the same
        object Python already has. Use this for anything you already have
        as a class - Reactor, Player, and so on."""
        self.nova.expose_global(name, value)

    def call(self, fn_name, *args):
        try:
            return self.nova.call(fn_name, *args)
        except NovaLangError as error:
            raise RuntimeError("NovaLang error in {}(): {}".format(fn_name, error)) from error
