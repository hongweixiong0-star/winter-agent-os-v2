"""``ContinuousTouchSession.__exit__`` must record *where* the failure was.

The module had no tests at all until this one, and the defect it pins is the shape the
role switch was fixed for on the same day: ``tb`` is handed to ``__exit__`` by the
interpreter and was ignored, so the abort reason carried only the exception's *name*
(``EXCEPTION_ValueError``).  One name then stood for any failure anywhere in the ``with``
block -- three different faults wearing one string, and nothing in the log could tell them
apart.  It cost a whole afternoon to tell a stale build from a recurrence.
"""
from __future__ import annotations

import unittest

from winter_agent_v2.continuous_touch import ContinuousTouchSession


def _traceback_of(exc: BaseException):
    return exc.__traceback__


class TheExitHandlerNamesTheFrameTests(unittest.TestCase):
    def test_the_abort_reason_carries_the_failing_frame(self):
        # ``object()`` is enough as the device: a session that has never gone down takes
        # ``abort``'s early path, which only records the reason.
        session = ContinuousTouchSession(object(), session_id="t")
        session._finger_down = True          # the physical truth ``holds_finger`` reports

        try:
            raise ValueError("boom")
        except ValueError as exc:
            session.__exit__(ValueError, exc, _traceback_of(exc))

        reason = session.report().reason
        self.assertIn("EXCEPTION_ValueError", reason)
        # The frame is the whole point: a name alone cannot be told from a stale build.
        self.assertIn("@", reason, reason)
        self.assertIn(".py:", reason, reason)

    def test_a_missing_traceback_is_tolerated(self):
        """``__exit__`` can be called with ``tb is None``; it must not raise on the way out."""
        session = ContinuousTouchSession(object(), session_id="t2")
        session._finger_down = True
        session.__exit__(ValueError, ValueError("no traceback"), None)
        self.assertIn("EXCEPTION_ValueError", session.report().reason)


if __name__ == "__main__":
    unittest.main()
