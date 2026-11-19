"""Virtual clock + priority event queue shared by all simulated devices."""

import heapq


class VirtualClock:
    """Nanosecond virtual time driven by executed instruction count."""

    def __init__(self, cpu_hz=400_000_000, cycles_per_insn=1):
        # 400 MHz is RZ/A1H max ceiling; conditional runtime clock is 384 MHz (both yield 2 ns/insn).
        self.now_ns = 0
        self.ns_per_insn = 1_000_000_000 // cpu_hz * cycles_per_insn
        self._events = []          # heap of (due_ns, seq, callback)
        self._seq = 0
        self.fired = 0

    def advance(self, insns):
        """Move time forward for executed instructions, firing due events."""
        self.now_ns += insns * self.ns_per_insn
        self._fire()

    def skip_to(self, target_ns):
        """Fast-forward while the CPU sleeps (WFI); fire everything due."""
        if target_ns > self.now_ns:
            self.now_ns = target_ns
        self._fire()

    def _fire(self):
        events = self._events
        while events and events[0][0] <= self.now_ns:
            _, _, callback = heapq.heappop(events)
            self.fired += 1
            reschedule = callback(self.now_ns)
            if reschedule is not None:      # callback returns next delay or None
                if reschedule < 1:          # guard against zero-delay storms
                    reschedule = 1
                heapq.heappush(events, (self.now_ns + reschedule, self._seq, callback))
                self._seq += 1

    def at(self, delay_ns, callback):
        """Schedule callback(now) at now + delay_ns."""
        heapq.heappush(self._events, (self.now_ns + delay_ns, self._seq, callback))
        self._seq += 1

    def next_due(self):
        return self._events[0][0] if self._events else None
