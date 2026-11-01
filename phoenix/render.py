"""Draw the phoenix as an animated SVG.

Notes on choices:
- Glow comes from radial gradients and opacity, never from filters. Blur
  filters on moving parts stutter in Safari and cost a lot everywhere.
- Animation is plain CSS inside the SVG, which GitHub keeps when it serves
  the file through an <img> tag.
- Output is deterministic for a given input, so the daily workflow only
  commits when something actually changed.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from heat import Activity

W, H = 480, 332
CX = 240

# deep, mid, bright, core
PALETTES = {
    "ash": ("#3f3f46", "#71717a", "#a1a1aa", "#d4d4d8"),
    "ember": ("#450a0a", "#7f1d1d", "#b91c1c", "#f97316"),
    "flame": ("#7c2d12", "#c2410c", "#f97316", "#fbbf24"),
    "blaze": ("#9a3412", "#ea580c", "#fb923c", "#fde047"),
    "inferno": ("#b45309", "#f97316", "#fde047", "#fffbeb"),
}
ASH_DARK = ("#52525b", "#a1a1aa", "#d4d4d8", "#f4f4f5")


@dataclass(frozen=True)
class Look:
    flap: float  # seconds per wingbeat, 0 means still
    lift: float  # wing upstroke in degrees
    glow: float  # peak glow opacity
    flame: float  # flame height multiplier, 0 means no fire
    embers: int
    ember_speed: float  # seconds for one ember to rise


LOOKS = {
    "ash": Look(0, 0, 0.10, 0, 3, 7.0),
    "ember": Look(3.2, 8, 0.28, 0.45, 5, 5.5),
    "flame": Look(2.2, 14, 0.42, 0.70, 9, 4.5),
    "blaze": Look(1.5, 20, 0.58, 0.92, 14, 3.6),
    "inferno": Look(1.0, 26, 0.78, 1.15, 22, 2.8),
}

TEXT = {"light": ("#1f2328", "#59636e"), "dark": ("#e6edf3", "#9198a1")}

SHOULDER = (226.0, 120.0)
TAIL_ROOT = (240.0, 180.0)


def _leaf(sx: float, sy: float, tx: float, ty: float, width: float, bend: float = 0.0) -> str:
    """A feather: two curves from root to tip, bulging to either side."""
    mx, my = (sx + tx) / 2, (sy + ty) / 2
    dx, dy = tx - sx, ty - sy
    length = math.hypot(dx, dy) or 1.0
    nx, ny = -dy / length, dx / length
    ax, ay = mx + nx * (width + bend), my + ny * (width + bend)
    bx, by = mx - nx * (width - bend), my - ny * (width - bend)
    return f"M{sx:.1f} {sy:.1f}Q{ax:.1f} {ay:.1f} {tx:.1f} {ty:.1f}Q{bx:.1f} {by:.1f} {sx:.1f} {sy:.1f}Z"


def _flame(x: float, base: float, h: float, w: float) -> str:
    top = base - h
    return (
        f"M{x - w:.1f} {base:.1f}"
        f"C{x - w:.1f} {base - h * 0.45:.1f} {x - w * 0.15:.1f} {base - h * 0.62:.1f} {x:.1f} {top:.1f}"
        f"C{x + w * 0.15:.1f} {base - h * 0.62:.1f} {x + w:.1f} {base - h * 0.45:.1f} {x + w:.1f} {base:.1f}"
        f"Q{x:.1f} {base + w * 0.6:.1f} {x - w:.1f} {base:.1f}Z"
    )


def _rand(i: int, salt: int) -> float:
    """Small deterministic hash in [0, 1)."""
    v = (i * 2654435761 + salt * 40503) & 0xFFFFFFFF
    v ^= v >> 15
    v = (v * 2246822519) & 0xFFFFFFFF
    v ^= v >> 13
    return (v & 0xFFFF) / 0x10000


def _wing(fill_back: str, fill_front: str) -> str:
    sx, sy = SHOULDER
    back = [(78, 38, 17, -5), (62, 78, 17, -4), (70, 116, 16, -2), (92, 148, 15, 0), (124, 168, 13, 2)]
    front = [(134, 70, 14, -3), (124, 102, 13, -2), (136, 132, 12, 0), (160, 150, 10, 2)]
    parts = [f'<path d="{_leaf(sx, sy, tx, ty, w, b)}" fill="url(#{fill_back})"/>' for tx, ty, w, b in back]
    parts += [
        f'<path d="{_leaf(sx + 4, sy + 2, tx, ty, w, b)}" fill="url(#{fill_front})"/>' for tx, ty, w, b in front
    ]
    return "".join(parts)


def _label(stage: str, a: Activity, h: float, reborn: bool) -> tuple[str, str]:
    title = stage.upper()
    if reborn:
        title = f"REBORN · {title}"
    detail = (
        f"heat {h:.2f} · {a.last_14:,} contributions in 14 days · "
        f"{a.last_60:,} in 60 · {round(a.active_ratio * 100)}% active days"
    )
    return title, detail


def render(stage: str, a: Activity, h: float, theme: str = "dark", reborn: bool = False) -> str:
    look = LOOKS[stage]
    deep, mid, bright, core = ASH_DARK if (stage == "ash" and theme == "dark") else PALETTES[stage]
    text, subtext = TEXT[theme]
    title, detail = _label(stage, a, h, reborn)
    lit = stage != "ash"

    css = [
        "text{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif}",
        f".t{{font-size:15px;font-weight:700;letter-spacing:2px;fill:{text}}}",
        f".d{{font-size:11.5px;fill:{subtext}}}",
        f"@keyframes glow{{0%,100%{{opacity:{look.glow * 0.7:.2f}}}50%{{opacity:{look.glow:.2f}}}}}",
        ".glow{animation:glow 3.4s ease-in-out infinite}",
    ]
    if look.flap:
        sx, sy = SHOULDER
        css += [
            f"@keyframes flap{{0%,100%{{transform:rotate(-12deg)}}50%{{transform:rotate({look.lift}deg)}}}}",
            f".wing{{transform-origin:{sx}px {sy}px;animation:flap {look.flap}s ease-in-out infinite}}",
            "@keyframes bob{0%,100%{transform:translateY(2px)}50%{transform:translateY(-6px)}}",
            f".bob{{animation:bob {look.flap}s ease-in-out infinite}}",
            "@keyframes sway{0%,100%{transform:rotate(-3deg)}50%{transform:rotate(3deg)}}",
            f".tail{{transform-origin:{TAIL_ROOT[0]}px {TAIL_ROOT[1]}px;"
            f"animation:sway {look.flap * 2:.1f}s ease-in-out infinite}}",
            ".crest{transform-origin:240px 66px;animation:sway 2.6s ease-in-out infinite}",
        ]
    else:
        css += [f".wing{{transform-origin:{SHOULDER[0]}px {SHOULDER[1]}px;transform:rotate(-38deg)}}"]
    if look.flame:
        css += [
            "@keyframes flick{0%,100%{transform:scale(1,1)}33%{transform:scale(.92,1.14)}"
            "66%{transform:scale(1.06,.9)}}",
            ".fl{transform-box:fill-box;transform-origin:50% 100%;animation:flick .9s ease-in-out infinite}",
        ]
    css += [
        "@keyframes rise{0%{transform:translateY(0);opacity:0}12%{opacity:1}100%{transform:translateY(-190px);opacity:0}}",
        ".em{animation:rise linear infinite}",
        "@keyframes smolder{0%,100%{opacity:.25}50%{opacity:.9}}",
        ".smolder{animation:smolder 2.8s ease-in-out infinite}",
    ]
    if reborn:
        css += [
            "@keyframes reborn{0%{transform:translateY(80px) scale(.25);opacity:0}"
            "35%{opacity:1}100%{transform:none;opacity:1}}",
            f".rb{{transform-origin:{CX}px 230px;animation:reborn 2.4s cubic-bezier(.2,.8,.2,1) .3s both}}",
            "@keyframes burst{0%{transform:scale(.1);opacity:1}100%{transform:scale(7);opacity:0}}",
            ".burst{transform-box:fill-box;transform-origin:50% 50%;animation:burst 1.6s ease-out .2s both}",
            "@keyframes flash{0%{opacity:0}20%{opacity:1}100%{opacity:0}}",
            ".flash{animation:flash 2.2s ease-out both}",
        ]
    css.append("@media (prefers-reduced-motion:reduce){*{animation:none!important}}")

    defs = f"""
<radialGradient id="g-glow" cx="50%" cy="50%" r="50%">
  <stop offset="0" stop-color="{bright}" stop-opacity=".9"/>
  <stop offset=".45" stop-color="{mid}" stop-opacity=".35"/>
  <stop offset="1" stop-color="{deep}" stop-opacity="0"/>
</radialGradient>
<radialGradient id="g-dot" cx="50%" cy="50%" r="50%">
  <stop offset="0" stop-color="{core}"/>
  <stop offset=".5" stop-color="{bright}" stop-opacity=".8"/>
  <stop offset="1" stop-color="{mid}" stop-opacity="0"/>
</radialGradient>
<linearGradient id="g-body" x1="0" y1="0" x2="0" y2="1">
  <stop offset="0" stop-color="{bright}"/>
  <stop offset=".55" stop-color="{mid}"/>
  <stop offset="1" stop-color="{deep}"/>
</linearGradient>
<linearGradient id="g-wb" gradientUnits="userSpaceOnUse" x1="{SHOULDER[0]}" y1="{SHOULDER[1]}" x2="70" y2="60">
  <stop offset="0" stop-color="{deep}"/>
  <stop offset=".6" stop-color="{mid}"/>
  <stop offset="1" stop-color="{bright}"/>
</linearGradient>
<linearGradient id="g-wf" gradientUnits="userSpaceOnUse" x1="{SHOULDER[0]}" y1="{SHOULDER[1]}" x2="130" y2="100">
  <stop offset="0" stop-color="{mid}"/>
  <stop offset="1" stop-color="{bright}"/>
</linearGradient>
<linearGradient id="g-tail" gradientUnits="userSpaceOnUse" x1="240" y1="180" x2="240" y2="280">
  <stop offset="0" stop-color="{mid}"/>
  <stop offset=".7" stop-color="{bright}"/>
  <stop offset="1" stop-color="{core}"/>
</linearGradient>
<linearGradient id="g-fo" x1="0" y1="1" x2="0" y2="0">
  <stop offset="0" stop-color="{bright}"/>
  <stop offset=".5" stop-color="{mid}"/>
  <stop offset="1" stop-color="{deep}" stop-opacity=".2"/>
</linearGradient>
<linearGradient id="g-fi" x1="0" y1="1" x2="0" y2="0">
  <stop offset="0" stop-color="{core}"/>
  <stop offset="1" stop-color="{bright}" stop-opacity=".3"/>
</linearGradient>"""

    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" '
        f'role="img" aria-labelledby="ttl">',
        f"<title id=\"ttl\">Git Phoenix: {title.lower()}, {detail}</title>",
        f"<style>{''.join(css)}</style>",
        f"<defs>{defs}</defs>",
        f'<circle class="glow" cx="{CX}" cy="150" r="150" fill="url(#g-glow)" opacity="{look.glow:.2f}"/>',
    ]

    if reborn:
        out.append(f'<circle class="flash" cx="{CX}" cy="200" r="120" fill="url(#g-dot)" opacity="0"/>')
        out.append(
            f'<circle class="burst" cx="{CX}" cy="232" r="12" fill="none" stroke="{bright}" '
            f'stroke-width="3" vector-effect="non-scaling-stroke"/>'
        )

    # Ash mound at the base: always present when dead or just reborn.
    if not lit or reborn:
        out.append(f'<ellipse cx="{CX}" cy="250" rx="70" ry="10" fill="{mid}" opacity=".55"/>')
        out.append(f'<ellipse cx="{CX}" cy="246" rx="44" ry="7" fill="{bright}" opacity=".45"/>')

    # Bird. Outer group handles rebirth, inner group the idle bob.
    out.append(f'<g class="{"rb" if reborn else ""}"><g class="bob">')

    tail = "".join(
        f'<path d="{_leaf(TAIL_ROOT[0], TAIL_ROOT[1], tx, ty, w, b)}" fill="url(#g-tail)"/>'
        for tx, ty, w, b in [(166, 262, 13, 16), (200, 280, 12, 8), (240, 288, 12, 0), (280, 280, 12, -8), (314, 262, 13, -16)]
    )
    tail += "".join(
        f'<circle cx="{x}" cy="{y}" r="4" fill="{core}" opacity="{0.9 if lit else 0.35}"/>'
        for x, y in [(174, 258), (205, 274), (240, 281), (275, 274), (306, 258)]
    )
    out.append(f'<g class="tail">{tail}</g>')

    wing = _wing("g-wb", "g-wf")
    out.append(f'<g><g class="wing">{wing}</g></g>')
    out.append(f'<g transform="translate({2 * CX} 0) scale(-1 1)"><g class="wing">{wing}</g></g>')

    body = "M240 70C258 70 262 92 255 110C270 130 266 166 240 188C214 166 210 130 225 110C218 92 222 70 240 70Z"
    out.append(f'<path d="{body}" fill="url(#g-body)"/>')
    out.append(f'<path d="M240 118C250 130 250 160 240 176C230 160 230 130 240 118Z" fill="{core}" opacity=".35"/>')

    crest = "".join(
        f'<path d="{_leaf(240, 70, tx, ty, w, b)}" fill="url(#g-body)"/>'
        for tx, ty, w, b in [(222, 38, 4, 3), (240, 30, 4, 0), (258, 38, 4, -3)]
    )
    crest += "".join(f'<circle cx="{x}" cy="{y}" r="2.6" fill="{core}"/>' for x, y in [(222, 38), (240, 30), (258, 38)])
    out.append(f'<g class="crest">{crest}</g>')

    eye = core if lit else deep
    out.append(f'<circle cx="233.5" cy="80" r="2.4" fill="{eye}"/><circle cx="246.5" cy="80" r="2.4" fill="{eye}"/>')
    out.append(f'<path d="M236 87L244 87L240 98Z" fill="{deep}"/>')

    if not lit:
        out.append(f'<circle class="smolder" cx="{CX}" cy="146" r="14" fill="url(#g-dot)"/>')
    out.append("</g></g>")

    # Fire bed in front of the tail root.
    if look.flame:
        k = look.flame
        for i, (dx, hh, ww) in enumerate([(-46, 40, 13), (-24, 58, 15), (0, 70, 17), (24, 58, 15), (46, 40, 13)]):
            x, delay = CX + dx, -_rand(i, 7) * 0.9
            out.append(
                f'<path class="fl" style="animation-delay:{delay:.2f}s" d="{_flame(x, 240, hh * k, ww)}" fill="url(#g-fo)"/>'
            )
            out.append(
                f'<path class="fl" style="animation-delay:{delay - 0.3:.2f}s" '
                f'd="{_flame(x, 240, hh * k * 0.55, ww * 0.55)}" fill="url(#g-fi)"/>'
            )

    for i in range(look.embers):
        x = CX - 110 + _rand(i, 1) * 220
        r = 1.2 + _rand(i, 2) * 2.0
        dur = look.ember_speed * (0.7 + _rand(i, 3) * 0.6)
        delay = -_rand(i, 4) * dur
        color = core if _rand(i, 5) > 0.5 else bright
        out.append(
            f'<circle class="em" style="animation-duration:{dur:.2f}s;animation-delay:{delay:.2f}s" '
            f'cx="{x:.1f}" cy="236" r="{r:.1f}" fill="{color}" opacity="0"/>'
        )

    out.append(f'<text class="t" x="{CX}" y="308" text-anchor="middle">{title}</text>')
    out.append(f'<text class="d" x="{CX}" y="325" text-anchor="middle">{detail}</text>')
    out.append("</svg>")
    return "\n".join(out) + "\n"
