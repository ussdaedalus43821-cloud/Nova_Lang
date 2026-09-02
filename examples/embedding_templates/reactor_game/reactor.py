"""reactor.py - the Reactor's state, trimmed to what rendering needs.

No decision-making left here on purpose - what used to be "if temp too
high, scram" Python code is now nova/reactor_control.nova. This class
just holds fields and the two primitive mutators NovaLang calls through
the live proxy (see nova_bridge.py's expose()): scram() and set_power().
Physics (tick) has moved to nova/reactor_physics.nova too, since that was
named as the first slice to port in the plan - keep it here instead, as
a normal method, if you'd rather port it later.
"""


class Reactor:
    def __init__(self):
        self.temp = 1800.0
        self.power = 70
        self.scrammed = False

    def scram(self):
        self.scrammed = True
        self.power = 0

    def set_power(self, power):
        self.power = max(0, min(100, power))
