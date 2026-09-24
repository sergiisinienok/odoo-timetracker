"""A real Odoo client that can be switched off mid-test — see test_phase2_gate.py."""

from tti.odoo.errors import OdooUnavailable


class SwitchableOdoo:
    """A real, working client until `down` is set — then every call raises
    OdooUnavailable, exactly as a dropped connection would."""

    def __init__(self, real):
        self._real = real
        self.down = False

    async def execute_kw(self, *args, **kwargs):
        if self.down:
            raise OdooUnavailable("simulated outage")
        return await self._real.execute_kw(*args, **kwargs)

    async def authenticate(self):
        if self.down:
            raise OdooUnavailable("simulated outage")
        return await self._real.authenticate()
