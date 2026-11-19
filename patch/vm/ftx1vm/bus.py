"""MMIO bus: routes guest peripheral accesses to device models.

Peripheral windows are mapped as plain RAM.  Read hooks substitute the
value the device model computes (write-into-RAM-then-continue, verified by
probe_unicorn3.py); write hooks inform the model while leaving the raw
value in RAM (harmless, and useful for debugging).

Accesses to unmapped addresses are logged once per page and satisfied as
0-returns/write-ignores so boot survives unknown registers; the log tells
us what still needs a model.
"""

import struct

from unicorn import (
    UC_HOOK_MEM_READ, UC_HOOK_MEM_WRITE,
    UC_HOOK_MEM_READ_UNMAPPED, UC_HOOK_MEM_WRITE_UNMAPPED,
)


class Bus:
    """Routes guest peripheral accesses to device models.

    Per-device read/write hooks are registered on the device window only —
    plain RAM traffic never enters Python (a global hook costs ~2 orders of
    magnitude in throughput).
    """

    def __init__(self, core, log=None):
        self.core = core
        self.devices = []
        self.by_name = {}
        self.unmapped_reads = {}        # page -> count
        self.unmapped_writes = {}
        self.log = log or (lambda *_: None)
        uc = core.uc
        uc.hook_add(UC_HOOK_MEM_READ_UNMAPPED, self._on_read_unmapped)
        uc.hook_add(UC_HOOK_MEM_WRITE_UNMAPPED, self._on_write_unmapped)

    def attach(self, device):
        base, size = device.BASE, device.SIZE
        self.core.map_ram(base, size)
        self.devices.append((base, size, device))
        self.by_name[device.NAME] = device
        device.bus = self
        uc = self.core.uc
        uc.hook_add(UC_HOOK_MEM_READ, self._make_reader(device),
                    begin=base, end=base + size - 1)
        uc.hook_add(UC_HOOK_MEM_WRITE, self._make_writer(device),
                    begin=base, end=base + size - 1)

    def _make_reader(self, device):
        base = device.BASE

        def on_read(uc, access, address, size, value, _user):
            data = device.read(address - base, size)
            if data is not None:
                uc.mem_write(address, data.to_bytes(size, "little"))
            return True
        return on_read

    def _make_writer(self, device):
        base = device.BASE

        def on_write(uc, access, address, size, value, _user):
            device.write(address - base, value, size)
            return True
        return on_write

    def _page_of(self, address):
        return address & ~0xFFF

    def _map_fallback(self, page):
        try:
            self.core.map_ram(page, 0x1000, quiet=True)
        except Exception:
            pass                            # partial overlap with existing maps

    def _on_read_unmapped(self, uc, access, address, size, value, _user):
        page = self._page_of(address)
        n = self.unmapped_reads.get(page, 0) + 1
        self.unmapped_reads[page] = n
        if n <= 3:
            self.log(f"[bus] unmapped read  {address:#010x} size={size} (page {page:#x} #{n})")
        self._map_fallback(page)
        try:
            uc.mem_write(address, bytes(size))     # reads as zero
        except Exception:
            pass
        return True

    def _on_write_unmapped(self, uc, access, address, size, value, _user):
        page = self._page_of(address)
        n = self.unmapped_writes.get(page, 0) + 1
        self.unmapped_writes[page] = n
        if n <= 3:
            self.log(f"[bus] unmapped write {address:#010x} size={size} value={value:#x} (page {page:#x} #{n})")
        self._map_fallback(page)
        return True
