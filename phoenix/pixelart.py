"""Shared pixel-art tools: color ramps, ordered dithering, a tiny font."""

from __future__ import annotations

import numpy as np

_BAYER_4 = np.array([[0, 8, 2, 10], [12, 4, 14, 6], [3, 11, 1, 9], [15, 7, 13, 5]], dtype=float)
BAYER_4 = (_BAYER_4 + 0.5) / 16

# Heat values where each stage looks exactly like its ramp.
ANCHORS = (("ember", 0.05), ("kindling", 0.32), ("blaze", 0.60), ("inferno", 0.90))

FIRE = {
    "ember": ("#12060c", "#2e0a12", "#571016", "#8a1a14", "#b52c12", "#d9480f", "#f0701a", "#f59a3a"),
    "kindling": ("#1c0710", "#4f0f14", "#8f1d10", "#c9360c", "#ee5a0c", "#f98216", "#fbab3a", "#fdd07a"),
    "blaze": ("#240812", "#6b1410", "#b82c0b", "#ea4e08", "#f97c0c", "#fba81b", "#fdd13e", "#fff08f"),
    "inferno": ("#3b0c14", "#a51c0e", "#e8400a", "#fb7a0a", "#fdab14", "#fed834", "#fff38a", "#ffffe6"),
}
# Turquoise plumage, a nod to the Southwest. It cools toward plum at low heat.
ACCENT_HOT = ("#0b1640", "#14307a", "#1a5fb0", "#1e96c8", "#27c7c9", "#5feac9", "#b4f7df", "#f0fff4")
ACCENT_COLD = ("#0c0a1e", "#1e1238", "#33184f", "#4a2068", "#5f2d7c", "#7a4294", "#9a62ab", "#bd8fc4")
# Magenta under the fire, for the depth a single orange ramp can't give.
MAGENTA_HOT = ("#2a0626", "#5c0d48", "#93126a", "#c91a7e", "#ee3a8c", "#fb6fa3", "#fda6c0", "#ffe0e6")
MAGENTA_COLD = ("#12060f", "#280b1f", "#40102c", "#5a1533", "#74203c", "#8e3448", "#a84f5c", "#c07a7e")
GOLD = ("#3b1c05", "#7a4208", "#b9700c", "#e6a013", "#f9c82e", "#fde469", "#fff3a8", "#fffde6")
ASH = ("#0d1016", "#22262e", "#3a3f49", "#565c67", "#767c87", "#989ea8", "#bcc1c9", "#e2e5ea")


def rgb(color: str) -> np.ndarray:
    return np.array([int(color[i:i + 2], 16) for i in (1, 3, 5)], dtype=float) / 255


def ramp(colors) -> np.ndarray:
    return np.stack([rgb(c) for c in colors])


def lerp(a, b, t):
    return a + (b - a) * t


def anchor_blend(h: float, table: dict) -> np.ndarray:
    """Blend the two stage entries that surround this heat value."""
    if h <= ANCHORS[0][1]:
        return ramp(table[ANCHORS[0][0]])
    for (s1, h1), (s2, h2) in zip(ANCHORS, ANCHORS[1:]):
        if h <= h2:
            return lerp(ramp(table[s1]), ramp(table[s2]), (h - h1) / (h2 - h1))
    return ramp(table[ANCHORS[-1][0]])


def bird_ramps(h: float, overrides: dict | None = None) -> np.ndarray:
    """Ramps indexed by part: 0 fire, 1 accent, 2 gold, 3 magenta. Shape (4, 8, 3)."""
    fire = {stage: tuple(colors) for stage, colors in FIRE.items()}
    for stage, colors in (overrides or {}).items():
        if stage in fire and isinstance(colors, (list, tuple)) and len(colors) == 8:
            fire[stage] = tuple(colors)
    accent = lerp(ramp(ACCENT_COLD), ramp(ACCENT_HOT), min(1.0, h / 0.6))
    magenta = lerp(ramp(MAGENTA_COLD), ramp(MAGENTA_HOT), min(1.0, h / 0.6))
    return np.stack([anchor_blend(h, fire), accent, ramp(GOLD), magenta])


def bayer_map(height: int, width: int) -> np.ndarray:
    return np.tile(BAYER_4, (height // 4 + 1, width // 4 + 1))[:height, :width]


def apply_ramp(value: np.ndarray, colors: np.ndarray, dither: np.ndarray) -> np.ndarray:
    """Map a 0..1 value buffer onto a ramp, dithering between its steps."""
    n = len(colors)
    index = np.clip((value * (n - 1) + dither).astype(int), 0, n - 1)
    return colors[index]


GLYPHS = {
    "A": "010101111101101", "B": "110101110101110", "C": "011100100100011", "D": "110101101101110",
    "E": "111100110100111", "F": "111100110100100", "G": "011100101101011", "H": "101101111101101",
    "I": "111010010010111", "J": "001001001101010", "K": "101101110101101", "L": "100100100100111",
    "M": "101111111101101", "N": "110101101101101", "O": "010101101101010", "P": "110101110100100",
    "Q": "010101101110011", "R": "110101110101101", "S": "011100010001110", "T": "111010010010010",
    "U": "101101101101111", "V": "101101101101010", "W": "101101111111101", "X": "101101010101101",
    "Y": "101101010010010", "Z": "111001010100111", "0": "111101101101111", "1": "010110010010111",
    "2": "111001111100111", "3": "110001010001110", "4": "101101111001001", "5": "111100110001110",
    "6": "011100110101010", "7": "111001010010010", "8": "010101010101010", "9": "010101011001110",
    "-": "000000111000000", ",": "000000000010100", ".": "000000000000010", "/": "001001010100100",
    " ": "000000000000000",
}


def text_mask(text: str, scale: int = 1) -> np.ndarray:
    """A boolean mask of the text in a 3x5 pixel font."""
    text = text.upper()
    width = max(1, len(text) * 4 - 1)
    mask = np.zeros((5, width), dtype=bool)
    for i, ch in enumerate(text):
        bits = GLYPHS.get(ch, GLYPHS[" "])
        glyph = np.array([c == "1" for c in bits]).reshape(5, 3)
        mask[:, i * 4:i * 4 + 3] = glyph
    return mask.repeat(scale, axis=0).repeat(scale, axis=1)


def stamp(frame: np.ndarray, mask: np.ndarray, x: int, y: int, color: np.ndarray) -> None:
    """Paint a mask onto a frame, clipped to its edges."""
    h, w = frame.shape[:2]
    y0, y1 = max(y, 0), min(y + mask.shape[0], h)
    x0, x1 = max(x, 0), min(x + mask.shape[1], w)
    if y0 < y1 and x0 < x1:
        frame[y0:y1, x0:x1][mask[y0 - y:y1 - y, x0 - x:x1 - x]] = color
