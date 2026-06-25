"""Reusable Manim stickman mobject for the mystery channel.

A stickman is a simple VGroup: head (circle), body (line), two arms and two
legs (lines). Built as a VGroup so it can be moved, scaled and animated as a
single unit. Kept deliberately minimal to match the channel's faceless,
low-cost visual style.

Imported lazily by the animation agent, so manim is only required when actually
rendering scenes.
"""
from __future__ import annotations

from manim import DOWN, LEFT, RIGHT, UP, Circle, Line, VGroup, WHITE


class Stickman(VGroup):
    """A simple white stickman centered around the origin."""

    def __init__(self, color=WHITE, stroke_width: float = 5, **kwargs):
        super().__init__(**kwargs)

        # Head sits above the body; body is the vertical trunk.
        self.head = Circle(radius=0.35, color=color, stroke_width=stroke_width)
        self.head.move_to(UP * 1.5)
        self.body = Line(UP * 1.15, DOWN * 0.2, color=color, stroke_width=stroke_width)

        # Arms branch out from the shoulders (top of the trunk).
        shoulder = UP * 0.95
        self.left_arm = Line(shoulder, shoulder + LEFT * 0.7 + DOWN * 0.4,
                             color=color, stroke_width=stroke_width)
        self.right_arm = Line(shoulder, shoulder + RIGHT * 0.7 + DOWN * 0.4,
                              color=color, stroke_width=stroke_width)

        # Legs branch out from the hips (bottom of the trunk).
        hip = DOWN * 0.2
        self.left_leg = Line(hip, hip + LEFT * 0.5 + DOWN * 0.9,
                             color=color, stroke_width=stroke_width)
        self.right_leg = Line(hip, hip + RIGHT * 0.5 + DOWN * 0.9,
                              color=color, stroke_width=stroke_width)

        self.add(
            self.head, self.body,
            self.left_arm, self.right_arm,
            self.left_leg, self.right_leg,
        )
