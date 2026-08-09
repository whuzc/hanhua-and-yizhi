"""Small, dependency-free visual primitives for the desktop release.

The release intentionally stays stdlib-only.  These primitives provide the
same visual language as the web version (soft glass surfaces, rounded cards,
liquid light and tactile controls) without requiring a browser engine or
shipping Android tooling.  Motion is decorative and can be disabled with
``GAME2APK_REDUCE_MOTION=1`` for accessibility/remote desktops.
"""

from __future__ import annotations

import ctypes
import math
import os
import tkinter as tk


BACKGROUND = "#edf7f2"
GLASS = "#f7fffc"
GLASS_HOVER = "#ffffff"
INK = "#263e3a"
MUTED = "#728b85"
MINT = "#2eb595"
MINT_DARK = "#1d7463"
EASE_OUT = (0.23, 1.0, 0.32, 1.0)


def apply_windows_backdrop(window: tk.Misc) -> None:
    """Best-effort Windows 11 Mica/acrylic backdrop.

    Tk remains the fallback on older Windows and non-Windows hosts.  No
    external DLL is loaded; failures are deliberately ignored so packaging
    and CLI behaviour stay unchanged.
    """

    if os.name != "nt":
        return
    try:
        hwnd = ctypes.windll.user32.GetParent(window.winfo_id()) or window.winfo_id()
        # DWMWA_SYSTEMBACKDROP_TYPE (38), DWMSBT_TRANSIENTWINDOW (3).
        value = ctypes.c_int(3)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 38, ctypes.byref(value), ctypes.sizeof(value))
        # DWMWA_USE_IMMERSIVE_DARK_MODE (20) is harmless when unsupported.
        dark = ctypes.c_int(0)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(dark), ctypes.sizeof(dark))
    except (AttributeError, OSError, TypeError):
        return


def _round_rect(canvas: tk.Canvas, x1: float, y1: float, x2: float, y2: float, radius: float, **kwargs: object) -> tuple[int, ...]:
    """Draw a seam-free rounded rectangle with separate fill and outline layers."""

    radius = max(1.0, min(radius, (x2 - x1) / 2, (y2 - y1) / 2))
    fill = kwargs.pop("fill", "")
    outline = kwargs.pop("outline", "")
    width = kwargs.pop("width", 1)
    tags = kwargs.pop("tags", "")
    ids: list[int] = [
        canvas.create_rectangle(x1 + radius, y1, x2 - radius, y2, fill=fill, outline="", tags=tags, **kwargs),
        canvas.create_rectangle(x1, y1 + radius, x2, y2 - radius, fill=fill, outline="", tags=tags, **kwargs),
        canvas.create_oval(x1, y1, x1 + radius * 2, y1 + radius * 2, fill=fill, outline="", tags=tags, **kwargs),
        canvas.create_oval(x2 - radius * 2, y1, x2, y1 + radius * 2, fill=fill, outline="", tags=tags, **kwargs),
        canvas.create_oval(x1, y2 - radius * 2, x1 + radius * 2, y2, fill=fill, outline="", tags=tags, **kwargs),
        canvas.create_oval(x2 - radius * 2, y2 - radius * 2, x2, y2, fill=fill, outline="", tags=tags, **kwargs),
    ]
    if outline:
        # A single continuous line/arc layer avoids the six visible seams
        # produced by giving every fill primitive its own outline.
        ids.extend([
            canvas.create_line(x1 + radius, y1, x2 - radius, y1, fill=outline, width=width, tags=tags),
            canvas.create_line(x1 + radius, y2, x2 - radius, y2, fill=outline, width=width, tags=tags),
            canvas.create_line(x1, y1 + radius, x1, y2 - radius, fill=outline, width=width, tags=tags),
            canvas.create_line(x2, y1 + radius, x2, y2 - radius, fill=outline, width=width, tags=tags),
            canvas.create_arc(x1, y1, x1 + radius * 2, y1 + radius * 2, start=90, extent=90, style="arc", outline=outline, width=width, tags=tags),
            canvas.create_arc(x2 - radius * 2, y1, x2, y1 + radius * 2, start=0, extent=90, style="arc", outline=outline, width=width, tags=tags),
            canvas.create_arc(x1, y2 - radius * 2, x1 + radius * 2, y2, start=180, extent=90, style="arc", outline=outline, width=width, tags=tags),
            canvas.create_arc(x2 - radius * 2, y2 - radius * 2, x2, y2, start=270, extent=90, style="arc", outline=outline, width=width, tags=tags),
        ])
    return tuple(ids)


class LiquidBackdrop(tk.Canvas):
    """Animated ambient light blobs behind the form.

    Only Canvas coordinates are animated (no layout/paint-heavy widget
    properties).  A short 32 ms tick keeps the effect subtle and interruptible
    while ``prefers-reduced-motion`` style behaviour is available through the
    environment switch.
    """

    def __init__(self, master: tk.Misc, *, reduced_motion: bool | None = None, **kwargs: object) -> None:
        super().__init__(master, background=BACKGROUND, highlightthickness=0, bd=0, **kwargs)
        self._reduced_motion = bool(reduced_motion) if reduced_motion is not None else os.environ.get("GAME2APK_REDUCE_MOTION", "").lower() in {"1", "true", "yes"}
        self._phase = 0.0
        self._last_size = (0, 0)
        self._blobs: list[tuple[int, float, float, float, float, str]] = []
        self._blob_shapes: list[tuple[int, ...]] = []
        self._seed_blobs()
        self.bind("<Configure>", self._resize, add="+")
        if not self._reduced_motion:
            self.after(32, self._tick)

    def _seed_blobs(self) -> None:
        # x/y are normalised coordinates, radius is a fraction of min(width,
        # height), amplitude and speed keep the movement gentle.
        self._blobs = [
            (0, 0.15, 0.13, 0.26, 0.48, "#c6eee1"),
            (1, 0.80, 0.20, 0.22, 0.37, "#d9e9ff"),
            (2, 0.67, 0.86, 0.28, 0.32, "#f2dfef"),
        ]

    def _resize(self, event: tk.Event[tk.Misc]) -> None:
        size = (max(1, int(event.width)), max(1, int(event.height)))
        if size == self._last_size:
            return
        self._last_size = size
        self._draw_blobs()

    def _draw_blobs(self) -> None:
        for shape in self._blob_shapes:
            for item in shape:
                self.delete(item)
        self._blob_shapes.clear()
        width, height = self._last_size
        if not width or not height:
            return
        radius_base = min(width, height)
        for _, nx, ny, radius, _, colour in self._blobs:
            cx = nx * width
            cy = ny * height
            r = radius * radius_base
            self._blob_shapes.append(_round_rect(self, cx - r, cy - r, cx + r, cy + r, r, fill=colour, outline="", tags="ambient"))
        self.tag_lower("ambient")

    def _tick(self) -> None:
        self._phase += 0.018
        width, height = self._last_size
        if width and height and self._blob_shapes:
            radius_base = min(width, height)
            for shape, (_, nx, ny, radius, speed, _) in zip(self._blob_shapes, self._blobs):
                dx = math.sin(self._phase * speed + nx * 7.0) * width * 0.018
                dy = math.cos(self._phase * speed * 0.83 + ny * 9.0) * height * 0.014
                r = radius * radius_base
                x1, y1, x2, y2 = nx * width + dx - r, ny * height + dy - r, nx * width + dx + r, ny * height + dy + r
                # The six primitives are kept in the same order by _round_rect.
                coords = ((x1 + r, y1, x2 - r, y2), (x1, y1 + r, x2, y2 - r), (x1, y1, x1 + r * 2, y1 + r * 2), (x2 - r * 2, y1, x2, y1 + r * 2), (x1, y2 - r * 2, x1 + r * 2, y2), (x2 - r * 2, y2 - r * 2, x2, y2))
                for item, box in zip(shape, coords):
                    self.coords(item, *box)
        self.after(32, self._tick)


class GlassCard(tk.Frame):
    """Rounded, raised card whose ``content`` frame hosts normal Tk widgets."""

    def __init__(self, master: tk.Misc, title: str = "", *, width: int = 0, height: int = 0, **kwargs: object) -> None:
        super().__init__(master, bg=BACKGROUND, bd=0, highlightthickness=0, **kwargs)
        self._surface = tk.Canvas(self, bg=BACKGROUND, highlightthickness=0, bd=0, width=width, height=height)
        self._surface.place(relx=0, rely=0, relwidth=1, relheight=1)
        self.content = tk.Frame(self, bg=GLASS, bd=0, highlightthickness=0)
        self.content.pack(fill="both", expand=True, padx=9, pady=9)
        self.title_label = tk.Label(self.content, text=title, bg=GLASS, fg=MINT_DARK, font=("Segoe UI", 10, "bold"), anchor="w") if title else None
        if self.title_label:
            self.title_label.pack(fill="x", padx=12, pady=(9, 3))
        # Consumers lay out fields with either pack or grid.  Keep the title
        # in the outer content frame and expose a dedicated body frame so the
        # two geometry managers never fight each other.
        self.body = tk.Frame(self.content, bg=GLASS, bd=0, highlightthickness=0)
        self.body.pack(fill="both", expand=True, padx=0, pady=(0, 2))
        self.content.bind("<Configure>", self._draw, add="+")
        self.bind("<Configure>", self._draw, add="+")
        self._draw()

    def _draw(self, _event: tk.Event[tk.Misc] | None = None) -> None:
        self._surface.delete("card")
        self._surface.delete("shadow")
        width, height = max(2, self.winfo_width()), max(2, self.winfo_height())
        # A single soft offset layer gives the card depth without the
        # segmented corner strokes that made the previous screenshot look
        # like square boxes with scratches around them.
        _round_rect(self._surface, 2, 4, width - 2, height, 18, fill="#d7eee7", outline="", tags="shadow")
        _round_rect(self._surface, 2, 2, width - 2, height - 2, 18, fill=GLASS, outline="#bfe6da", width=1, tags="card")
        self._surface.tag_lower("card")
        self._surface.tag_lower("shadow")


class GlassButton(tk.Button):
    """Native Tk button with rounded-ish glass styling and press feedback."""

    def __init__(self, master: tk.Misc, **kwargs: object) -> None:
        kwargs.setdefault("bg", MINT)
        kwargs.setdefault("activebackground", MINT_DARK)
        kwargs.setdefault("fg", "#ffffff")
        kwargs.setdefault("activeforeground", "#ffffff")
        kwargs.setdefault("relief", "flat")
        kwargs.setdefault("bd", 0)
        kwargs.setdefault("highlightthickness", 0)
        kwargs.setdefault("cursor", "hand2")
        kwargs.setdefault("padx", 16)
        kwargs.setdefault("pady", 8)
        kwargs.setdefault("font", ("Segoe UI", 10, "bold"))
        normal_bg = str(kwargs.get("bg", MINT))
        normal_fg = str(kwargs.get("fg", "#ffffff"))
        hover_bg = str(kwargs.pop("hover_bg", MINT_DARK if normal_bg == MINT else "#c3ecdf"))
        hover_fg = str(kwargs.pop("hover_fg", "#ffffff" if normal_bg == MINT else MINT_DARK))
        super().__init__(master, **kwargs)
        self._normal_bg = normal_bg
        self._normal_fg = normal_fg
        self._hover_bg = hover_bg
        self._hover_fg = hover_fg
        self.bind("<Enter>", lambda _event: self.configure(bg=self._hover_bg, fg=self._hover_fg), add="+")
        self.bind("<Leave>", lambda _event: self.configure(bg=self._normal_bg, fg=self._normal_fg), add="+")
        self.bind("<ButtonPress-1>", lambda _event: self.configure(relief="sunken", padx=15, pady=9), add="+")
        self.bind("<ButtonRelease-1>", lambda _event: self.configure(relief="flat", padx=16, pady=8), add="+")
