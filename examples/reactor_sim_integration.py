#!/usr/bin/env python3
"""
examples/reactor_sim_integration.py - Stage 12's embedding API, driving a
reactor simulation from a NovaLang control script.

This is a runnable, self-contained MOCK of the pattern for wiring NovaLang
into a real simulation such as Reactor Sim: the `Reactor` class below is a
small stand-in with the same shape (temp, power, scram(), set_power()) a
real one would have. Swap it for your actual reactor object and this
script's structure - load the control script once, call check_reactor()
once per tick - carries over directly.

Run: python3 examples/reactor_sim_integration.py
"""

import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from novalang import Nova, NovaLangError  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))


class Reactor:
    """A minimal mock reactor - enough state to exercise
    examples/reactor_script.nova's checks. Replace with your real sim's
    reactor object; nothing here is NovaLang-specific."""

    def __init__(self):
        self.temp = 1800.0
        self.power = 70
        self.scrammed = False

    def scram(self):
        self.scrammed = True
        self.power = 0

    def set_power(self, power):
        self.power = max(0, min(100, power))

    def tick(self):
        """Advance the simulation by one step - purely illustrative
        physics, not a real reactor model."""
        if self.scrammed:
            self.temp = max(20.0, self.temp - 40)
            return
        self.temp += self.power * 6 + random.uniform(-15, 25)
        self.temp = max(20.0, self.temp)


def main():
    nova = Nova()
    nova.load_file(os.path.join(HERE, "reactor_script.nova"))

    reactor = Reactor()
    print("tick  temp     power  scrammed  result")
    for tick in range(1, 21):
        try:
            result = nova.call("check_reactor", reactor)
        except NovaLangError as error:
            # A bug in the control script should not take the simulation
            # down with it - report it and keep the reactor running under
            # whatever state it was already in.
            print("control script error:", error)
            result = "script_error"
        print(
            "{:>4}  {:>7.1f}  {:>5}  {:>8}  {}".format(
                tick, reactor.temp, reactor.power, reactor.scrammed, result
            )
        )
        if reactor.scrammed and reactor.temp < 200:
            print("reactor cooled down after scram; stopping")
            break
        reactor.tick()


if __name__ == "__main__":
    main()
