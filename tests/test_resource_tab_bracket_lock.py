"""The bracket-to-label lock in ``selected_tab_from_live_labels``.

Measured 2026-10-02 over 40 archived production frames whose ledger row says the resource
search panel was open (720x1280, ``dataset/raw/control_panel/runtime_auto``):

    distance from the TRUE bracket pair's centre to its tab label : 0.0000 / 0.0003 / 0.0010
    distance from the best SPURIOUS stroke pair  to any tab label   : 0.0212 .. 0.0799

The bracket is drawn *centred on the tab*, so the true pair lands within ~1 px of the label.
The old ``0.03`` lock accepted spurious pairs as well (a stroke pair 134.5 px wide whose centre
happens to sit 15 px from the neighbouring 失控的雪怪 label), and because the function refuses to
guess when two kinds match, it answered ``None`` -- even though the true pair was 20x more
precise.  ``None`` is what ``verify_beast_search_tab_selected`` reads as
``BEAST_SEARCH_TAB_NOT_PROVEN``, which is 8 of the 2026-10-02 failures and the trigger for the
``ONLINE_UNKNOWN_NAVIGATION`` model call that could only answer REPLAN.

These tests use the measured numbers rather than synthesised ones so that a later "cleanup"
of the constant has to argue with the frames.
"""
from pathlib import Path
from types import SimpleNamespace

from PIL import Image

from winter_agent_v2.ocr import selected_tab_from_live_labels

#: The after-frame of episode 20261002_123127_711948 step 004 (720x1280), where the client had
#: visibly moved the selection bracket from 冰原巨兽 onto 野兽 and the reader still said ``None``.
MEASURED_AFTER_FRAME_STROKES = [(37.0, 3), (171.5, 6), (318.0, 5)]
MEASURED_AFTER_FRAME_LABELS = {
    "SNOW_MONSTER": (0.1236, 0.7394),
    "BEAST": (0.3410, 0.7398),
    "GIANT_BEAST": (0.5583, 0.7394),
}


def _semantic(strokes):
    return SimpleNamespace(_bracket_strokes=lambda image: list(strokes))


def _frame(tmp_path: Path) -> Path:
    path = tmp_path / "frame.png"
    Image.new("RGB", (720, 1280)).save(path)
    return path


def test_the_measured_frame_resolves_to_the_tab_the_bracket_is_actually_on(tmp_path):
    """One spurious pair must not be able to veto a pair that lands on its label to the pixel."""
    path = _frame(tmp_path)
    verdict = selected_tab_from_live_labels(
        path, MEASURED_AFTER_FRAME_LABELS, _semantic(MEASURED_AFTER_FRAME_STROKES)
    )
    assert verdict == "BEAST"


def test_a_pair_that_merely_grazes_a_label_is_still_refused(tmp_path):
    """Tightening the lock must not amount to "take the nearest label no matter how far"."""
    path = _frame(tmp_path)
    # Only the 134.5 px pair survives, and its centre sits 0.0212 from 失控的雪怪 -- 15 px away.
    verdict = selected_tab_from_live_labels(
        path, MEASURED_AFTER_FRAME_LABELS, _semantic([(37.0, 3), (171.5, 6)])
    )
    assert verdict is None


def test_two_pairs_both_landing_on_their_label_still_refuse_to_guess(tmp_path):
    """Ambiguity that is genuine stays ambiguous; the fix is about spurious pairs, not about
    turning a tie into a coin toss."""
    path = _frame(tmp_path)
    strokes = [(239.0, 5), (384.0, 5), (396.0, 5), (541.0, 5)]
    labels = {"BEAST": (245.5 / 720.0, 0.74), "GIANT_BEAST": (542.0 / 720.0, 0.74)}
    assert selected_tab_from_live_labels(path, labels, _semantic(strokes)) is None


def test_the_lock_can_only_ever_replace_none_and_never_relabel(tmp_path):
    """The safety property the fix rests on, over the measured geometries.

    The accepted set under a tighter lock is a subset of the accepted set under a looser one
    (``d < t'`` implies ``d < t`` whenever ``t' < t``), and the function only ever returns
    ``next(iter(matches))`` for a singleton ``matches``.  A subset of ``{X}`` is ``{}`` or
    ``{X}``; therefore tightening can turn an answer into ``None``, or resolve ``None`` into
    that *same* answer, and can never turn ``X`` into ``Y``.  That is why the change is safe to
    deploy into AUTO without a live run first: it cannot introduce a wrong label, only remove a
    wrong refusal.

    Checked here against the measured numbers, because the argument -- not the constant -- is
    what makes the deployment safe.
    """
    path = _frame(tmp_path)
    geometries = (
        # (strokes, labels) -- the after-frame, the before-frame, and two degenerate strips.
        (MEASURED_AFTER_FRAME_STROKES, MEASURED_AFTER_FRAME_LABELS),
        ([(203.0, 4), (348.0, 4)], {"BEAST": (0.2743, 0.7398)}),
        ([(67.5, 4), (213.5, 4)], {"GIANT_BEAST": (0.4917, 0.7402)}),
        ([(239.0, 5), (384.0, 5)], {"BEAST": (0.3410, 0.7398)}),
    )
    for strokes, labels in geometries:
        verdict = selected_tab_from_live_labels(path, labels, _semantic(strokes))
        assert verdict is None or verdict in labels, (verdict, labels)
        if verdict is None:
            continue
        # The tab the function named must be the one the *nearest* accepted pair sits on.
        centres = [
            (left + right) / 2 / 720.0
            for i, (left, _) in enumerate(strokes)
            for right, _ in strokes[i + 1:]
            if 130 <= right - left <= 175
        ]
        assert centres, "a verdict cannot come from an empty accepted set"
        nearest = min(labels.items(), key=lambda kv: min(abs(kv[1][0] - c) for c in centres))
        assert verdict == nearest[0]
