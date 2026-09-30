"""Nightly learning: group what the day failed to read, and ask about one frame per group.

Operator directive 2026-10-01, sections 21-23.  The runtime accumulates screens it could not read
-- unnamed pages, unlocated controls, verifier failures, loop screenshots -- and by the end of a
day that pile is large.  Asking the model about each of them is exactly the cost this whole
milestone exists to remove, so the pile is **grouped first**:

    ~1000 unknown frames -> pHash clustering -> ~23 visual states -> one representative each

and only the representatives would ever be shown to a model.  Section 22 states the ratio as the
goal; the reason it works is that an unread screen is unread *for a reason* -- the same overlay, the
same event panel, the same maintenance banner -- so most of the pile is the same screen photographed
a thousand times.

What this module is and is not
------------------------------
It is **grouping plus candidate knowledge**: pure functions over files already on disk, writing
JSON under ``knowledge/offline/``.  It never opens a device, never taps, and never writes to the
registry -- its output is ``CandidatePageKnowledge`` / ``CandidateUiSemantic`` /
``FailurePatternCandidate`` / ``CandidateSkill`` suggestions, each carrying the episodes it came
from.

It is not a scheduler and holds no clock.  When it runs is the operator's business (a cron, a
tool invocation, an idle check); *what* it does is here, so the same function serves an interactive
look and the unattended pass.

The clustering is deliberate about two things
---------------------------------------------
* **pHash on the whole frame, not on the control crop.**  The question "is this the same screen?"
  is about the screen: two different overlays can contain the same 关闭 crop, and grouping on the
  crop would merge them and then propose one name for two pages.
* **the representative is the medoid, not the first member.**  An arbitrary member may be the one
  odd frame -- a mid-animation capture, a partially-loaded panel -- and the whole point of picking
  one frame per group is that the one frame has to be typical.  The medoid minimises the sum of
  distances to the other members, which is the cheapest available definition of "typical".
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from . import image_hash

#: Where the offline analysis writes.  ``knowledge/`` rather than ``learning/`` because the output
#: is candidate *knowledge*: it outlives the run that produced it and is read by the same loaders
#: that read the rest of ``knowledge/``.
OFFLINE_DIR = Path("knowledge/offline")
CLUSTERS_PATH = OFFLINE_DIR / "unknown_clusters.json"
CANDIDATE_DIR = OFFLINE_DIR / "candidates"

#: Where the runtime leaves the screens it could not read.  These are the existing stores, not new
#: ones -- section 21's list is a list of *sources*, and the project already keeps every one of
#: them under ``knowledge/perception``.
PAGE_STORE_DIR = Path("knowledge/perception/pages")
ELEMENT_STORE_DIR = Path("knowledge/perception/candidates")
UNKNOWN_REQUEST_DIR = Path("learning/unknown_requests")

#: How different two frames must be before they are called different screens.  Measured on this
#: project's own frames: two captures of one static screen differ by 0-2 bits (the clock and the
#: resource ticker), while two different overlays differ by 12+ on the 64-bit digest.  Six is the
#: midpoint, and it is stated as a distance rather than a similarity threshold because hamming
#: distance is what the digest is for.
CLUSTER_MAX_DISTANCE = 6

#: A frame that appeared once is not a visual state worth naming -- it is a transient.  Groups at
#: or above this size are the ones that would be worth a model call.
MIN_CLUSTER_SIZE = 2

#: The failure types whose frames belong in the pile.  Read from the episode stream, so this is a
#: filter over what really happened rather than a list of things someone imagined.
FAILURE_TYPES: tuple[str, ...] = (
    "UNKNOWN_PAGE",
    "UNKNOWN_POPUP",
    "SEMANTIC_TARGET_NOT_FOUND",
    "SEMANTIC_TARGET_NOT_VERIFIED",
    "TARGET_NOT_FOUND",
    "VERIFY_FAILED",
    "NO_EXECUTION",
    "PAGE_NOT_OPEN",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class OfflineFrame:
    """One picture in the pile, with where it came from.  Provenance is not optional (section 44:
    *"禁止没有来源的 Knowledge"*), so a frame without a source episode is not accepted at all."""

    frame_path: str
    source: str            # PAGES / ELEMENTS / UNKNOWN_REQUEST / FAILURE_EPISODE
    episode_id: str = ""
    page_key: str = ""
    goal_id: str = ""
    failure_type: str = ""
    image_path: str = ""   # what to hash: the frame, or a page/element record's own picture

    @property
    def hash_target(self) -> str:
        return self.image_path or self.frame_path

    def as_row(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class UnknownCluster:
    """One visual state, with a representative frame and the evidence it came from."""

    cluster_id: str
    size: int
    representative: OfflineFrame
    members: tuple[OfflineFrame, ...] = ()
    #: Up to two further frames, so a model can be shown one variant without being shown the pile.
    variants: tuple[OfflineFrame, ...] = ()
    sources: tuple[str, ...] = ()
    failure_types: tuple[str, ...] = ()
    episode_ids: tuple[str, ...] = ()
    page_keys: tuple[str, ...] = ()
    first_seen: str = ""
    last_seen: str = ""
    #: What the clustering itself can say without a model.  Candidate knowledge, not confirmed.
    candidate_knowledge: tuple[dict[str, Any], ...] = ()

    def as_row(self) -> dict[str, Any]:
        return {
            "schema_version": "1.0",
            "recorded_at": _now(),
            "cluster_id": self.cluster_id,
            "size": self.size,
            "status": "CANDIDATE",
            "representative": self.representative.as_row(),
            "variants": [frame.as_row() for frame in self.variants],
            "members": [frame.as_row() for frame in self.members],
            "sources": list(self.sources),
            "failure_types": list(self.failure_types),
            "episode_ids": list(self.episode_ids),
            "page_keys": list(self.page_keys),
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
            "candidate_knowledge": [dict(item) for item in self.candidate_knowledge],
            "not_yet": (
                "CANDIDATE only -- clustering says these frames look alike, not what they are. "
                "Naming needs a model or a real navigation, and either way confirmation is the "
                "existing OBSERVED -> CONFIRMED path's decision."
            ),
        }


# ---------------------------------------------------------------------------- sources
def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return dict(payload) if isinstance(payload, Mapping) else None


def frames_from_page_store(root: Path | str = PAGE_STORE_DIR) -> list[OfflineFrame]:
    """Every page the model read as UNKNOWN, with the picture that was kept for it."""
    out: list[OfflineFrame] = []
    directory = Path(root)
    if not directory.exists():
        return out
    for path in sorted(directory.glob("*/record.json")):
        payload = _read_json(path)
        if not payload:
            continue
        label = str(payload.get("page_label") or payload.get("page") or "")
        if label and label.upper() not in ("UNKNOWN", ""):
            continue
        picture = str(payload.get("image_path") or "")
        out.append(OfflineFrame(
            frame_path=str(payload.get("source_frame") or ""),
            image_path=str(directory / path.parent.name / "page.png") if not picture else picture,
            source="PAGES",
            episode_id=str(payload.get("source_episode") or ""),
            page_key=str(payload.get("key") or path.parent.name),
        ))
    return out


def frames_from_unknown_requests(root: Path | str = UNKNOWN_REQUEST_DIR) -> list[OfflineFrame]:
    """Every question the runtime filed, with the frame it filed it about."""
    out: list[OfflineFrame] = []
    directory = Path(root)
    if not directory.exists():
        return out
    for path in sorted(directory.glob("*.json")):
        payload = _read_json(path)
        if not payload:
            continue
        out.append(OfflineFrame(
            frame_path=str(payload.get("frame_path") or ""),
            source="UNKNOWN_REQUEST",
            page_key=str(payload.get("page_key") or ""),
            goal_id=str(payload.get("goal") or ""),
            failure_type=str(payload.get("unknown_type") or ""),
        ))
    return out


def frames_from_failures(
    episodes: Iterable[Mapping[str, Any]],
) -> list[OfflineFrame]:
    """Failed steps whose verdict a screenshot could explain (section 23's raw material)."""
    out: list[OfflineFrame] = []
    for row in episodes:
        failure = str(row.get("failure_type") or "")
        if failure.split(":")[0].strip() not in FAILURE_TYPES:
            continue
        frame = str(row.get("after_screenshot") or row.get("before_screenshot") or "")
        if not frame:
            continue
        out.append(OfflineFrame(
            frame_path=frame,
            source="FAILURE_EPISODE",
            episode_id=str(row.get("episode_id") or ""),
            page_key=str(row.get("before_page") or ""),
            goal_id=str(row.get("goal_id") or ""),
            failure_type=failure,
        ))
    return out


def dedupe(frames: Iterable[OfflineFrame]) -> list[OfflineFrame]:
    """One entry per picture path.  A frame referenced by two stores is one observation."""
    seen: set[str] = set()
    out: list[OfflineFrame] = []
    for frame in frames:
        key = str(frame.hash_target)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(frame)
    return out


# ---------------------------------------------------------------------------- clustering
@dataclass(frozen=True)
class _Hashed:
    frame: OfflineFrame
    digest: str


def hash_frames(
    frames: Sequence[OfflineFrame],
    *,
    hasher: Any = None,
) -> list[_Hashed]:
    """Digest the frames that can be read, skipping the rest.

    A missing or unreadable picture is dropped rather than replaced with a placeholder: the point
    of clustering is that a group means "these look alike", and a group built on a stand-in image
    would mean nothing while looking exactly the same in the report.
    """
    if hasher is None:
        from PIL import Image  # imported here so the module is importable without Pillow

        def hasher(path: str) -> str:
            with Image.open(path) as image:
                return image_hash.phash(image.convert("RGB"))

    out: list[_Hashed] = []
    for frame in frames:
        try:
            out.append(_Hashed(frame=frame, digest=str(hasher(frame.hash_target))))
        except (OSError, ValueError, ImportError):
            continue
    return out


def cluster_hashes(
    hashed: Sequence[_Hashed],
    *,
    max_distance: int = CLUSTER_MAX_DISTANCE,
    min_size: int = MIN_CLUSTER_SIZE,
) -> list[list[_Hashed]]:
    """Greedy medoid clustering: each frame joins the nearest group within ``max_distance``.

    Greedy rather than k-means because the number of states is not known in advance and because
    this has to be explainable: "this frame is within 6 bits of the group's first member" is a
    sentence a reviewer can check, which a centroid of a 64-bit digest is not.

    The groups that are too small to name are still returned, so the caller can report how much of
    the pile was transients instead of quietly dropping it.
    """
    groups: list[list[_Hashed]] = []
    centroids: list[str] = []
    for item in hashed:
        best = -1
        best_distance = max_distance + 1
        for index, centroid in enumerate(centroids):
            distance = image_hash.hamming(item.digest, centroid)
            if distance < best_distance:
                best, best_distance = index, distance
        if best >= 0:
            groups[best].append(item)
        else:
            groups.append([item])
            centroids.append(item.digest)
    return [group for group in groups if len(group) >= min_size]


def _medoid(group: Sequence[_Hashed]) -> _Hashed:
    """The member closest to all the others -- "typical" as a measurement, not as a guess."""
    if len(group) == 1:
        return group[0]
    best = group[0]
    best_total = None
    for candidate in group:
        total = sum(image_hash.hamming(candidate.digest, other.digest) for other in group)
        if best_total is None or total < best_total:
            best, best_total = candidate, total
    return best


# ---------------------------------------------------------------------------- candidate knowledge
def suggest_candidate_knowledge(
    *,
    group: Sequence[_Hashed],
    representative: _Hashed,
) -> tuple[dict[str, Any], ...]:
    """What the *group itself* supports, with no model involved.

    Only two kinds of statement are made, and both are true by construction:

    * a **recurrence** -- "this visual state occurred N times across M sessions", which is the
      evidence a naming decision would need;
    * a **failure-pattern candidate** -- the failure types the group's members carried, which is
      section 23's raw material before any model looks at it.

    Nothing here names the page.  A name is a claim about the game, and the only honest sources for
    one are a model's proposal (a candidate) or a real navigation (which is not available offline).
    """
    items: list[dict[str, Any]] = []
    failure_types = sorted({
        frame.failure_type for item in group for frame in (item.frame,) if frame.failure_type
    })
    episodes = sorted({item.frame.episode_id for item in group if item.frame.episode_id})
    items.append({
        "kind": "UnknownVisualStateCandidate",
        "status": "CANDIDATE",
        "occurrences": len(group),
        "distinct_episodes": len(episodes),
        "evidence_episodes": episodes[:20],
        "representative_frame": representative.frame.hash_target,
        "note": (
            "a recurring unread visual state; naming it needs a model proposal or a real "
            "navigation, and either way the confirmation path is OBSERVED -> CONFIRMED"
        ),
    })
    if failure_types:
        items.append({
            "kind": "FailurePatternCandidate",
            "status": "CANDIDATE",
            "failure_types": failure_types,
            "occurrences": len(group),
            "evidence_episodes": episodes[:20],
            "note": (
                "these failures share one screen; it is a candidate, not a recovery rule -- a rule "
                "needs repeated evidence and a verifier, per section 23"
            ),
        })
    return tuple(items)


def cluster_id(representative: _Hashed, group: Sequence[_Hashed]) -> str:
    """A stable id from the group's *own* membership, so re-running the analysis on the same pile
    lands on the same ids instead of forking a new set of files."""
    material = "|".join(sorted(item.frame.hash_target for item in group))
    stem = hashlib.sha256(material.encode("utf-8")).hexdigest()[:10]
    return f"UNK_{stem}"


def build_clusters(
    frames: Sequence[OfflineFrame],
    *,
    hasher: Any = None,
    max_distance: int = CLUSTER_MAX_DISTANCE,
    min_size: int = MIN_CLUSTER_SIZE,
) -> tuple[UnknownCluster, ...]:
    """The whole offline pass: hash, group, pick a representative, suggest knowledge.  Pure."""
    hashed = hash_frames(frames, hasher=hasher)
    groups = cluster_hashes(hashed, max_distance=max_distance, min_size=min_size)
    out: list[UnknownCluster] = []
    for group in groups:
        representative = _medoid(group)
        ordered = sorted(group, key=lambda item: item.frame.hash_target)
        variants = tuple(item.frame for item in ordered if item is not representative)[:2]
        out.append(UnknownCluster(
            cluster_id=cluster_id(representative, group),
            size=len(group),
            representative=representative.frame,
            members=tuple(item.frame for item in ordered),
            variants=variants,
            sources=tuple(sorted({item.frame.source for item in group})),
            failure_types=tuple(sorted({
                item.frame.failure_type for item in group if item.frame.failure_type
            })),
            episode_ids=tuple(sorted({
                item.frame.episode_id for item in group if item.frame.episode_id
            })),
            page_keys=tuple(sorted({
                item.frame.page_key for item in group if item.frame.page_key
            })),
            first_seen=str(getattr(representative.frame, "recorded_at", "") or ""),
            last_seen="",
            candidate_knowledge=suggest_candidate_knowledge(
                group=group, representative=representative
            ),
        ))
    out.sort(key=lambda cluster: (-cluster.size, cluster.cluster_id))
    return tuple(out)


def write_clusters(
    clusters: Sequence[UnknownCluster],
    *,
    out_dir: Path | str = OFFLINE_DIR,
    write_individual: bool = True,
) -> dict[str, Any]:
    """Persist the pass.  Returns the summary that goes in the console and the report."""
    directory = Path(out_dir)
    summary = {
        "schema_version": "1.0",
        "written_at": _now(),
        "clusters": len(clusters),
        "frames_in_clusters": sum(cluster.size for cluster in clusters),
        "largest_cluster": max((cluster.size for cluster in clusters), default=0),
        "candidate_knowledge": sum(len(cluster.candidate_knowledge) for cluster in clusters),
        "representative_frames": [cluster.representative.hash_target for cluster in clusters],
        "records": [{
            "cluster_id": cluster.cluster_id,
            "size": cluster.size,
            "representative": cluster.representative.hash_target,
            "sources": list(cluster.sources),
            "failure_types": list(cluster.failure_types),
            "episodes": len(cluster.episode_ids),
        } for cluster in clusters],
    }
    try:
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "unknown_clusters.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        if write_individual:
            candidates = directory / CANDIDATE_DIR.name
            candidates.mkdir(parents=True, exist_ok=True)
            for cluster in clusters:
                (candidates / f"{cluster.cluster_id}.json").write_text(
                    json.dumps(cluster.as_row(), ensure_ascii=False, indent=1), encoding="utf-8"
                )
    except (OSError, TypeError, ValueError):
        pass
    return summary


def run_offline_pass(
    *,
    root: Path | str = ".",
    episodes: Iterable[Mapping[str, Any]] = (),
    hasher: Any = None,
    write: bool = True,
) -> dict[str, Any]:
    """The nightly entry point: collect every source, group, and report.

    ``root`` is where the stores live, so a tool can run this against a checked-out tree or against
    a production worktree without changing a module global -- the same discipline the rest of the
    project's stores follow.
    """
    base = Path(root)
    frames: list[OfflineFrame] = []
    frames.extend(frames_from_page_store(base / PAGE_STORE_DIR))
    frames.extend(frames_from_unknown_requests(base / UNKNOWN_REQUEST_DIR))
    frames.extend(frames_from_failures(episodes))
    unique = dedupe(frames)
    clusters = build_clusters(unique, hasher=hasher)
    summary = {
        "sources": {
            "frames_seen": len(frames),
            "frames_after_dedupe": len(unique),
        },
        "clusters": len(clusters),
        "frames_in_clusters": sum(cluster.size for cluster in clusters),
        "candidate_knowledge": sum(len(cluster.candidate_knowledge) for cluster in clusters),
        "representative_frames": [cluster.representative.hash_target for cluster in clusters],
        "reduction": (
            f"{len(unique)} frame(s) -> {len(clusters)} visual state(s)"
            if unique else "nothing to group"
        ),
    }
    if write:
        written = write_clusters(clusters, out_dir=base / OFFLINE_DIR)
        summary["written"] = written
    return summary
