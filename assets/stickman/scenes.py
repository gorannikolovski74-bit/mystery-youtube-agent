"""Scene vocabulary for the mystery channel — backgrounds, props, and motion.

A small library of Manim building blocks so the animation agent can compose
varied, topic-relevant scenes instead of a single static stickman:

  * backgrounds: night sky + stars + moon, mountain silhouettes, snow ground
  * props: tent, pine trees, magnifier, document, footprints, question marks
  * characters: a walking stickman and a group of hikers
  * scene builders: intro, journey, night camp, discovery, investigation,
    theory, conclusion — each animates for a requested duration.

Everything is faceless stick-art in the channel palette (dark navy background,
white figures, gold accents). Imported lazily by animation_agent (needs manim).
"""
from __future__ import annotations

import numpy as np
from manim import (
    DOWN,
    LEFT,
    RIGHT,
    UP,
    Circle,
    Create,
    Dot,
    FadeIn,
    FadeOut,
    Line,
    Polygon,
    Rectangle,
    RoundedRectangle,
    Text,
    VGroup,
    Write,
    rate_functions,
)

from assets.stickman.stickman import Stickman

# Palette (mirrors config/style_profile.md).
BG = "#1a1a2e"
WHITE = "#FFFFFF"
GOLD = "#FFD700"
SNOW = "#cfd8e8"
MOUNTAIN = "#33334d"
MOON = "#f3efc8"

# Frame extents (Manim 16:9 default): x ~[-7.1, 7.1], y ~[-4, 4].
LEFT_X, RIGHT_X = -7.1, 7.1
GROUND_Y = -2.6


# --- Backgrounds -------------------------------------------------------------
def night_sky(seed: int = 0) -> VGroup:
    """Stars scattered in the upper sky plus a pale moon (static group)."""
    rng = np.random.default_rng(seed)
    stars = VGroup()
    for _ in range(40):
        x = rng.uniform(LEFT_X, RIGHT_X)
        y = rng.uniform(0.2, 3.8)
        stars.add(Dot([x, y, 0], radius=rng.uniform(0.012, 0.035), color=WHITE))
    moon = Circle(radius=0.55, color=MOON, fill_opacity=1, stroke_width=0)
    moon.move_to([4.8, 2.7, 0])
    return VGroup(stars, moon)


def mountains() -> VGroup:
    """Jagged mountain silhouette filling the lower third."""
    pts = [
        [LEFT_X, GROUND_Y, 0], [-5.5, -0.4, 0], [-3.8, -1.6, 0],
        [-2.2, 0.1, 0], [-0.5, -1.3, 0], [1.3, -0.2, 0],
        [3.0, -1.7, 0], [4.8, -0.5, 0], [RIGHT_X, GROUND_Y, 0],
        [RIGHT_X, -4.2, 0], [LEFT_X, -4.2, 0],
    ]
    return Polygon(*pts, color=MOUNTAIN, fill_opacity=1, stroke_width=0)


def snow_ground() -> Polygon:
    """A flat snow field across the very bottom of the frame."""
    return Polygon(
        [LEFT_X, GROUND_Y, 0], [RIGHT_X, GROUND_Y, 0],
        [RIGHT_X, -4.2, 0], [LEFT_X, -4.2, 0],
        color=SNOW, fill_opacity=1, stroke_width=0,
    )


# --- Props -------------------------------------------------------------------
def pine(x: float, scale: float = 1.0) -> VGroup:
    """A simple pine tree (stacked triangles) standing on the ground."""
    base_y = GROUND_Y
    trunk = Line([x, base_y, 0], [x, base_y + 0.25, 0], color=WHITE, stroke_width=3)
    body = Polygon(
        [x - 0.4 * scale, base_y + 0.2, 0],
        [x + 0.4 * scale, base_y + 0.2, 0],
        [x, base_y + 1.1 * scale, 0],
        color=WHITE, stroke_width=3,
    )
    return VGroup(trunk, body)


def tent(center=(0.0, -1.9), cut: bool = False) -> VGroup:
    """A triangular tent; `cut` adds a gold slash to imply the cut-open tent."""
    cx, cy = center
    body = Polygon(
        [cx - 1.0, cy - 0.7, 0], [cx + 1.0, cy - 0.7, 0], [cx, cy + 0.7, 0],
        color=WHITE, stroke_width=4,
    )
    pole = Line([cx, cy + 0.7, 0], [cx, cy - 0.7, 0], color=WHITE, stroke_width=3)
    group = VGroup(body, pole)
    if cut:
        slash = Line([cx - 0.1, cy + 0.45, 0], [cx + 0.25, cy - 0.55, 0],
                     color=GOLD, stroke_width=5)
        group.add(slash)
    return group


def magnifier() -> VGroup:
    """A magnifying glass (investigation prop)."""
    lens = Circle(radius=0.45, color=GOLD, stroke_width=5)
    handle = Line(
        lens.get_center() + np.array([0.32, -0.32, 0]),
        lens.get_center() + np.array([0.8, -0.8, 0]),
        color=GOLD, stroke_width=6,
    )
    return VGroup(lens, handle)


def document() -> VGroup:
    """A clue document: a rounded rectangle with text lines."""
    paper = RoundedRectangle(width=3.0, height=3.8, corner_radius=0.12,
                             color=WHITE, stroke_width=4)
    lines = VGroup()
    for i in range(6):
        y = 1.2 - i * 0.45
        lines.add(Line([-1.1, y, 0], [1.1, y, 0], color=WHITE, stroke_width=2))
    return VGroup(paper, lines)


def footprints(start_x: float = -4.0, count: int = 6) -> VGroup:
    """A trail of small footprints across the snow."""
    prints = VGroup()
    for i in range(count):
        x = start_x + i * 1.3
        y = GROUND_Y - 0.25 + (0.12 if i % 2 else -0.12)
        prints.add(Circle(radius=0.08, color=BG, fill_opacity=1,
                          stroke_color=MOUNTAIN, stroke_width=2).move_to([x, y, 0]))
    return prints


def question_marks(center=(0.0, 1.5)) -> VGroup:
    """A cluster of gold question marks for 'theory/mystery' beats."""
    cx, cy = center
    marks = VGroup()
    for dx, dy, s in [(-1.6, 0.2, 0.9), (0, 0.6, 1.3), (1.6, 0.1, 0.9)]:
        marks.add(Text("?", color=GOLD, weight="BOLD").scale(s).move_to(
            [cx + dx, cy + dy, 0]))
    return marks


# --- Characters --------------------------------------------------------------
def hikers(n: int = 3) -> VGroup:
    """A row of small stickmen (a hiking group)."""
    group = VGroup()
    for i in range(n):
        s = Stickman(color=WHITE, stroke_width=4).scale(0.55)
        s.shift(RIGHT * (i * 1.1))
        group.add(s)
    return group


# --- Scene builders ----------------------------------------------------------
# Each builder adds mobjects to the given Scene and animates for ~`duration`
# seconds, then returns. They assume self.camera.background_color is set.

def _fill_time(scene, seconds: float) -> None:
    if seconds > 0:
        scene.wait(seconds)


def build_intro(scene, duration: float) -> None:
    sky = night_sky(seed=7)
    scene.add(sky)
    q = Text("?", color=GOLD, weight="BOLD").scale(3.5)
    scene.play(FadeIn(sky, run_time=1.0))
    scene.play(Write(q), run_time=1.2)
    scene.play(q.animate.scale(1.15), rate_func=rate_functions.ease_in_out_sine,
               run_time=1.0)
    _fill_time(scene, duration - 3.2)


def build_journey(scene, duration: float) -> None:
    scene.add(night_sky(seed=3), mountains(), snow_ground())
    scene.add(pine(-6.2, 0.9), pine(6.0, 1.1))
    group = hikers(3).move_to([LEFT_X - 1.5, GROUND_Y + 0.6, 0])
    scene.add(group)
    walk = max(2.0, duration - 1.0)
    scene.play(group.animate.move_to([RIGHT_X + 1.5, GROUND_Y + 0.6, 0]),
               rate_func=rate_functions.linear, run_time=walk)
    _fill_time(scene, duration - walk)


def build_night_camp(scene, duration: float) -> None:
    scene.add(night_sky(seed=11), mountains(), snow_ground())
    t = tent(center=(1.4, -1.9))
    person = Stickman(color=WHITE, stroke_width=4).scale(0.6)
    person.move_to([-1.6, GROUND_Y + 0.7, 0])
    scene.play(Create(t), run_time=1.2)
    scene.play(FadeIn(person), run_time=0.8)
    scene.play(person.animate.shift(RIGHT * 0.8),
               rate_func=rate_functions.ease_in_out_sine, run_time=1.2)
    _fill_time(scene, duration - 3.2)


def build_discovery(scene, duration: float) -> None:
    scene.add(mountains(), snow_ground())
    t = tent(center=(2.2, -1.9), cut=True)
    scene.add(t)
    prints = footprints(start_x=-4.5, count=6)
    person = Stickman(color=WHITE, stroke_width=4).scale(0.6)
    person.move_to([-5.0, GROUND_Y + 0.7, 0])
    scene.add(person)
    # Footprints appear one by one toward the tent.
    for p in prints:
        scene.play(FadeIn(p, run_time=min(0.35, duration / (len(prints) + 4))))
    scene.play(person.animate.shift(RIGHT * 0.4 + UP * 0.2), run_time=0.6)
    _fill_time(scene, duration - (0.35 * len(prints) + 0.6))


def build_investigation(scene, duration: float) -> None:
    scene.add(night_sky(seed=5))
    doc = document().shift(LEFT * 1.2)
    glass = magnifier().move_to(doc.get_corner(UP + LEFT) + np.array([0.4, -0.4, 0]))
    scene.play(FadeIn(doc), run_time=1.0)
    scene.play(FadeIn(glass), run_time=0.5)
    sweep = max(1.5, duration - 2.5)
    scene.play(glass.animate.move_to(doc.get_corner(DOWN + RIGHT) +
               np.array([-0.4, 0.4, 0])),
               rate_func=rate_functions.ease_in_out_sine, run_time=sweep)
    _fill_time(scene, duration - sweep - 1.5)


def build_theory(scene, duration: float) -> None:
    scene.add(night_sky(seed=9))
    person = Stickman(color=WHITE, stroke_width=5).scale(0.9).shift(DOWN * 0.3)
    scene.play(Create(person), run_time=1.0)
    marks = question_marks(center=(0.0, 1.6))
    for m in marks:
        scene.play(FadeIn(m, shift=UP * 0.2), run_time=0.5)
    _fill_time(scene, duration - 1.0 - 0.5 * len(marks))


def build_conclusion(scene, duration: float) -> None:
    scene.add(night_sky(seed=2), mountains(), snow_ground())
    person = Stickman(color=WHITE, stroke_width=4).scale(0.6)
    person.move_to([-1.0, GROUND_Y + 0.7, 0])
    scene.add(person)
    walk = max(2.0, duration - 1.5)
    scene.play(person.animate.move_to([RIGHT_X + 1.0, GROUND_Y + 0.7, 0]),
               rate_func=rate_functions.ease_in_out_sine, run_time=walk)
    q = Text("?", color=GOLD, weight="BOLD").scale(2.0).move_to([0, 1.0, 0])
    scene.play(FadeIn(q), run_time=1.0)
    _fill_time(scene, duration - walk - 1.0)


# Registry + a sensible default narrative arc when no director is available.
TEMPLATES = {
    "intro": build_intro,
    "journey": build_journey,
    "night_camp": build_night_camp,
    "discovery": build_discovery,
    "investigation": build_investigation,
    "theory": build_theory,
    "conclusion": build_conclusion,
}

TEMPLATE_DESCRIPTIONS = {
    "intro": "opening hook; gold question mark over a starry sky",
    "journey": "people travelling/hiking across mountains and snow",
    "night_camp": "night scene with a tent; setting the scene / background",
    "discovery": "finding something strange; cut tent, footprints, evidence",
    "investigation": "examining clues/documents with a magnifier",
    "theory": "competing explanations; figure surrounded by question marks",
    "conclusion": "unresolved ending; lone figure walking away into mountains",
}

DEFAULT_ARC = [
    "intro", "night_camp", "journey", "night_camp", "discovery",
    "discovery", "investigation", "theory", "investigation", "theory",
]


def default_template_for(index: int, total: int) -> str:
    """Pick a template by position when no Claude director is used."""
    if index == 0:
        return "intro"
    if index == total - 1:
        return "conclusion"
    return DEFAULT_ARC[index % len(DEFAULT_ARC)]
