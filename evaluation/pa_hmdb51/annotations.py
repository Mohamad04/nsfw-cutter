"""PA-HMDB51 privacy-attribute annotations: parsing and their (non-)relation to NSFW categories.

File format (verified on the official PrivacyAttributes/*.json, one file per HMDB51 action):
  {"<hmdb51 file name>.avi": {"face" | "gender" | "skin_color" | "nudity" | "relationship":
                                  [[first_frame, last_frame, value], ...],
                              "review": bool, "note": str}}
Frame indices are 0-based and inclusive, in decoded-frame order (checked against FFmpeg's decode of
the original AVI: a [0, 258] range covers exactly the 259 decoded frames). A value is an int or, for
coexisting people, a list of ints. Frames without any person are not annotated (paper, footnote 4).

Value meanings come from Table 1 of Wu et al., TPAMI 2020 (arXiv:1906.05675). The "review" flag and
"note" are not documented by the dataset and are recorded without interpretation.

PA-HMDB51 "nudity" is a clothing-exposure scale (long sleeves and pants / short sleeves, skirts or
shorts / half-naked body). It is NOT a reference label for any NSFW Cutter category: no level states
that genitals, buttocks or a female areola are visible, and nothing describes sexual activity or a
sexual context. The relation of each value to the project's categories is stated in RELATION.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

ATTRIBUTES = ("face", "gender", "skin_color", "nudity", "relationship")
PAPER = "Wu, Wang, Wang, Jin, Wang. Privacy-Preserving Deep Action Recognition. TPAMI 2020, arXiv:1906.05675, Table 1"

MEANING = {
    "skin_color": {0: "unidentifiable", 1: "white", 2: "brown/yellow", 3: "black", 4: "different skin colors coexisting"},
    "face": {0: "invisible (<10% visible)", 1: "partially visible (10-70%)", 2: "completely visible (>70%)"},
    "gender": {0: "unidentifiable", 1: "male", 2: "female", 3: "different genders coexisting"},
    "nudity": {0: "no nudity: long sleeves and pants", 1: "partial nudity: short sleeves, skirts or shorts",
               2: "semi-nudity: half-naked body"},
    "relationship": {0: "personal relationship unidentifiable", 1: "personal relationship identifiable"},
}

# usability: how a value may be used in this evaluation (never as a verified NSFW reference label).
#   covariate             descriptive stratification only, unrelated to NSFW categories
#   presumption           strong hint that project 'nudity' is absent for annotated people; still unverified
#   needs_human_review    compatible with both 'absent' and 'present' under the project guide
RELATION = {
    "nudity": {
        0: ("presumption", "Clothed annotated people: project 'nudity' presumed absent (not verified; "
                           "unannotated frames, screens or posters are not covered)."),
        1: ("presumption", "Short sleeves, skirts or shorts: absent under guide 4.1 (legs, shoulders); still unverified."),
        2: ("needs_human_review", "Half-naked body: a bare male torso, swimwear or underwear is 'absent' under guide "
                                  "4.1, a visible female areola or bare buttocks is 'present'; human review required."),
    },
    "relationship": {
        0: ("covariate", "No NSFW meaning."),
        1: ("covariate", "Intimate relationship identifiable (friends, couple, family): not sexual activity or "
                         "sexual context; a kiss is 'absent' under guide 4.2/4.3."),
    },
    "face": {v: ("covariate", "No NSFW meaning.") for v in MEANING["face"]},
    "gender": {v: ("covariate", "No NSFW meaning.") for v in MEANING["gender"]},
    "skin_color": {v: ("covariate", "No NSFW meaning.") for v in MEANING["skin_color"]},
}
NOT_COVERED = ("sexual_activity", "sexual_context")

# HMDB51 file names: <source>_<action>_<body>_<camera>_<people>_<viewpoint>_<quality>_<clip>.avi
# (meta tags of Kuehne et al., ICCV 2011).
HMDB_TAIL = (r"_(?P<body>[fhlu])_(?P<camera>cm|nm)_(?P<people>np\d)_(?P<viewpoint>fr|ba|le|ri)_"
             r"(?P<quality>bad|med|goo)_(?P<clip>\d+)\.avi$")
HMDB_TAGS = {"body": {"f": "full body", "h": "head", "l": "lower body", "u": "upper body"},
             "camera": {"cm": "camera motion", "nm": "no camera motion"},
             "viewpoint": {"fr": "front", "ba": "back", "le": "left", "ri": "right"},
             "quality": {"bad": "bad", "med": "medium", "goo": "good"}}


@dataclass(frozen=True)
class Segment:
    attribute: str
    first_frame: int
    last_frame: int
    values: tuple[int, ...]

    @property
    def frames(self) -> int:
        return self.last_frame - self.first_frame + 1


@dataclass
class VideoAnnotation:
    file_name: str
    segments: list[Segment]
    review: object
    note: str
    issues: list[str] = field(default_factory=list)

    def attribute(self, name: str) -> list[Segment]:
        return [s for s in self.segments if s.attribute == name]

    def annotated_frames(self, name: str) -> int:
        return sum(s.frames for s in self.attribute(name))

    def extent(self):
        return min(s.first_frame for s in self.segments), max(s.last_frame for s in self.segments)

    def nudity_frames(self) -> dict[int, int]:
        """Frames per nudity level; a frame with coexisting levels counts for each of them."""
        counts = {0: 0, 1: 0, 2: 0}
        for segment in self.attribute("nudity"):
            for value in segment.values:
                counts[value] = counts.get(value, 0) + segment.frames
        return counts

    def max_nudity(self) -> int | None:
        values = [v for s in self.attribute("nudity") for v in s.values]
        return max(values) if values else None


def _values(raw) -> tuple[int, ...]:
    values = tuple(raw) if isinstance(raw, list) else (raw,)
    if not values or any(type(v) is not int for v in values):
        raise ValueError(f"unexpected attribute value {raw!r}")
    return values


def parse_video(file_name: str, entry: dict) -> VideoAnnotation:
    unknown = set(entry) - {*ATTRIBUTES, "review", "note"}
    if unknown:
        raise ValueError(f"{file_name}: unexpected keys {sorted(unknown)}")
    segments, issues = [], []
    for attribute in ATTRIBUTES:
        rows = entry.get(attribute)
        if not rows:
            issues.append(f"{attribute}: missing")
            continue
        previous = None
        for row in rows:
            if len(row) != 3 or type(row[0]) is not int or type(row[1]) is not int or row[1] < row[0] or row[0] < 0:
                raise ValueError(f"{file_name}: malformed {attribute} segment {row!r}")
            segment = Segment(attribute, row[0], row[1], _values(row[2]))
            undefined = [v for v in segment.values if v not in MEANING[attribute]]
            if undefined:
                issues.append(f"{attribute}: undefined value(s) {undefined}")
            if previous is not None and segment.first_frame < previous.first_frame:
                raise ValueError(f"{file_name}: unordered {attribute} segments")
            if previous is not None and segment.first_frame <= previous.last_frame:
                # Present in the official files (e.g. hug.json): kept as is and reported.
                issues.append(f"{attribute}: frames {segment.first_frame}-{previous.last_frame} annotated twice")
            elif previous is not None and segment.first_frame != previous.last_frame + 1:
                issues.append(f"{attribute}: frames {previous.last_frame + 1}-{segment.first_frame - 1} unannotated")
            previous = segment
            segments.append(segment)
        if rows[0][0] != 0:
            issues.append(f"{attribute}: frames 0-{rows[0][0] - 1} unannotated")
    annotation = VideoAnnotation(file_name, segments, entry.get("review"), entry.get("note", ""), issues)
    ends = {s.attribute: s.last_frame for s in segments}
    if len(set(ends.values())) > 1:
        annotation.issues.append(f"attributes end on different frames: {ends}")
    return annotation


def load_action(path: Path) -> dict[str, VideoAnnotation]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return {name: parse_video(name, entry) for name, entry in data.items()}


def parse_hmdb_name(file_name: str, action: str) -> dict:
    """The action is given (it is the archive name): action names may contain underscores."""
    match = re.match(r"^(?P<source>.+)_" + re.escape(action) + HMDB_TAIL, file_name)
    if not match:
        return {"source": None, "action": action, "parsed": False}
    tags = match.groupdict()
    return {**tags, "action": action, "clip": int(tags["clip"]), "people": int(tags["people"][2:]), "parsed": True}


def relation(attribute: str, value: int):
    return RELATION.get(attribute, {}).get(value, ("needs_human_review", "Value not defined by the dataset paper."))


def inventory(directory: Path) -> dict:
    """Per-action counts over every PrivacyAttributes file (annotations only, no media)."""
    rows = {}
    for path in sorted(Path(directory).glob("*.json")):
        videos = load_action(path)
        levels = [v.max_nudity() for v in videos.values()]
        rows[path.stem] = {"annotated_videos": len(videos),
                           "max_nudity_level_counts": {str(k): levels.count(k) for k in (0, 1, 2)},
                           "review_true": sum(v.review is True for v in videos.values()),
                           "videos_with_issues": sum(bool(v.issues) for v in videos.values())}
    return rows
