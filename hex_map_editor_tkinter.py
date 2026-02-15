"""
Realm Brew Hex Map Editor — Tkinter version
Requires only Pillow:  pip3 install pillow
Run with:             python3 hex_map_editor_tkinter.py
"""

import tkinter as tk
from tkinter import filedialog, messagebox
from pathlib import Path
import json
import math
import re
from PIL import Image, ImageTk

# ─── Colours ──────────────────────────────────────────────────────────────────
BG            = "#14161e"
PANEL_BG      = "#1e2130"
PANEL_BORDER  = "#3c4158"
GRID_COL      = "#3c4150"
GRID_HOVER    = "#7882a0"
GRID_SEL      = "#dcb43c"
GRID_SEL_OV   = "#ff9932"
ACCENT        = "#64a0ff"
TEXT          = "#d2d7e6"
TEXT_DIM      = "#787d91"

BTN_BG        = "#ffffff"
BTN_FG        = "#111111"
BTN_HOVER_BG  = "#e0e0e0"
BTN_ACTIVE_BG = "#c8d8ff"
BTN_ACTIVE_FG = "#111133"
BTN_RED_BG    = "#fde0e0"
BTN_RED_FG    = "#7a1010"
BTN_GRN_BG    = "#d4f0d4"
BTN_GRN_FG    = "#1a5c1a"

HEX_SIZE_DEFAULT    = 60
MIN_HEX_SIZE        = 20
MAX_HEX_SIZE        = 160
SIDEBAR_W           = 330
THUMB               = 72
ROTATIONS           = 6
OVERLAY_SCALE_DEFAULT = 0.5   # fraction of hex diameter


# ─── Realm Brew folder detection ──────────────────────────────────────────────

def _clean_display_name(folder_name: str) -> str:
    name = re.sub(r"^\d\s*[•·]\s*", "", folder_name)
    for strip in ["Realm Brew - ", "Realm Brew "]:
        if name.startswith(strip):
            name = name[len(strip):]
            break
    for suffix in [" - Digital Tiles", " - Digital Overlays",
                   " Digital Tiles", " Digital Overlays",
                   " Tiles", " Overlays"]:
        if name.endswith(suffix):
            name = name[:-len(suffix)]
            break
    return name.strip()


def _is_overlay_folder(name: str) -> bool:
    return "overlay" in name.lower()


def _is_tile_folder(name: str) -> bool:
    low = name.lower()
    return any(k in low for k in ("tile", "dungeon", "river", "cavern",
                                   "subterranean", "underdark"))


# ─── Hex math (flat-top) ──────────────────────────────────────────────────────

def hex_corners(cx, cy, size):
    pts = []
    for i in range(6):
        a = math.radians(60 * i)
        pts += [cx + size * math.cos(a), cy + size * math.sin(a)]
    return pts


def hex_to_pixel(col, row, size):
    return size * 1.5 * col, size * math.sqrt(3) * (row + 0.5 * (col & 1))


def pixel_to_hex(px, py, size):
    col = int(round(px / (size * 1.5)))
    best, best_d = (col, 0), float("inf")
    for dc in (-1, 0, 1):
        for dr in (-2, -1, 0, 1, 2):
            c = col + dc
            r = int(round(py / (size * math.sqrt(3)) - 0.5 * (c & 1))) + dr
            hx, hy = hex_to_pixel(c, r, size)
            d = (px - hx) ** 2 + (py - hy) ** 2
            if d < best_d:
                best_d, best = d, (c, r)
    return best


# ─── Data classes ─────────────────────────────────────────────────────────────

class TileInfo:
    def __init__(self, path, category, display_category):
        self.path, self.category, self.display_category = Path(path), category, display_category
        self.name = Path(path).stem.replace("_", " ").replace("-", " ").title()


class OverlayInfo:
    def __init__(self, path, category, display_category):
        self.path, self.category, self.display_category = Path(path), category, display_category
        self.name = Path(path).stem.replace("_", " ").replace("-", " ").title()


class PlacedTile:
    def __init__(self, col, row, path, category, rotation=0):
        self.col, self.row, self.path = col, row, str(path)
        self.category, self.rotation  = category, rotation


class PlacedOverlay:
    def __init__(self, col, row, path, offset_x=0, offset_y=0,
                 rotation=0, scale=OVERLAY_SCALE_DEFAULT):
        self.col, self.row, self.path = col, row, str(path)
        self.offset_x, self.offset_y  = offset_x, offset_y
        self.rotation, self.scale      = rotation, scale


class HexMap:
    def __init__(self):
        self.tiles, self.overlays, self.filepath = {}, [], None

    def save(self, path):
        data = {
            "tiles": [{"col": t.col, "row": t.row, "path": t.path,
                        "category": t.category, "rotation": t.rotation}
                       for t in self.tiles.values()],
            "overlays": [{"col": o.col, "row": o.row, "path": o.path,
                           "offset_x": o.offset_x, "offset_y": o.offset_y,
                           "rotation": o.rotation, "scale": o.scale}
                          for o in self.overlays]
        }
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
        self.filepath = path

    def load(self, path):
        with open(path) as f:
            data = json.load(f)
        self.tiles = {(t["col"], t["row"]): PlacedTile(
            t["col"], t["row"], t["path"], t.get("category", ""), t.get("rotation", 0))
            for t in data.get("tiles", [])}
        self.overlays = [PlacedOverlay(
            o["col"], o["row"], o["path"],
            o.get("offset_x", 0), o.get("offset_y", 0),
            o.get("rotation", 0), o.get("scale", OVERLAY_SCALE_DEFAULT))
            for o in data.get("overlays", [])]
        self.filepath = path


# ─── Image cache ──────────────────────────────────────────────────────────────

class ImageCache:
    def __init__(self):
        self._pil, self._photo = {}, {}

    def _pil_img(self, path):
        s = str(path)
        if s not in self._pil:
            self._pil[s] = Image.open(s).convert("RGBA")
        return self._pil[s]

    def get_tile_photo(self, path, hex_size, rotation_steps):
        size = int(hex_size * 2)
        key  = ("t", str(path), size, rotation_steps)
        if key not in self._photo:
            img = self._pil_img(path).copy().resize((size, size), Image.LANCZOS)
            if rotation_steps:
                img = img.rotate(-rotation_steps * 60, expand=False)
            self._photo[key] = ImageTk.PhotoImage(img)
        return self._photo[key]

    def get_overlay_photo(self, path, hex_size, scale, rotation_deg):
        base = max(int(hex_size * 2 * scale), 4)
        rot  = round(rotation_deg) % 360
        key  = ("o", str(path), base, rot)
        if key not in self._photo:
            raw = self._pil_img(path)
            asp = raw.height / max(raw.width, 1)
            img = raw.copy().resize((base, max(int(base * asp), 4)), Image.LANCZOS)
            if rot:
                img = img.rotate(-rot, expand=True, resample=Image.BICUBIC)
            self._photo[key] = ImageTk.PhotoImage(img)
        return self._photo[key]

    def get_thumb(self, path, size=68):
        key = ("th", str(path), size)
        if key not in self._photo:
            img = self._pil_img(path).copy()
            img.thumbnail((size, size), Image.LANCZOS)
            bg  = Image.new("RGBA", (size, size), (40, 40, 55, 255))
            bg.paste(img, ((size - img.width) // 2, (size - img.height) // 2), img)
            self._photo[key] = ImageTk.PhotoImage(bg)
        return self._photo[key]


# ─── Library ──────────────────────────────────────────────────────────────────

class TileLibrary:
    def __init__(self):
        self.categories, self.overlay_categories = {}, {}
        self.cache = ImageCache()

    def load(self, root):
        self.categories, self.overlay_categories = {}, {}
        for d in sorted(Path(root).iterdir()):
            if not d.is_dir():
                continue
            pngs = sorted(d.glob("*.png"))
            if not pngs:
                continue
            display = _clean_display_name(d.name)
            if _is_overlay_folder(d.name):
                self.overlay_categories[display] = [
                    OverlayInfo(p, d.name, display) for p in pngs]
            else:
                self.categories[display] = [
                    TileInfo(p, d.name, display) for p in pngs]
        return bool(self.categories) or bool(self.overlay_categories)


# ─── Application ──────────────────────────────────────────────────────────────

class App:
    def __init__(self, root):
        self.root = root
        self.root.title("Realm Brew Hex Map Editor")
        self.root.configure(bg=BG)
        self.root.geometry("1440x860")
        self.root.minsize(900, 600)

        self.library  = TileLibrary()
        self.hex_map  = HexMap()
        self.hex_size = HEX_SIZE_DEFAULT
        self.cam_x, self.cam_y = 550.0, 380.0

        self.mode             = "view"
        self.hovered_hex      = None
        self.selected_hex     = None
        self.sel_category     = None
        self.sel_tile_idx     = None
        self.placement_rot    = 0
        self.sel_ov_category  = None
        self.sel_overlay_idx  = None
        self.selected_ov_idx  = None

        self._pan_start_mouse = None
        self._pan_start_cam   = None
        self._drag_ov_idx     = None
        self._drag_ov_offset  = (0, 0)
        self._photo_refs      = []
        self._thumb_refs      = []

        self._build_ui()
        self._prompt_folder()

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        # Top bar
        topbar = tk.Frame(self.root, bg=PANEL_BG, height=52)
        topbar.pack(side=tk.TOP, fill=tk.X)
        topbar.pack_propagate(False)

        tk.Label(topbar, text="⬡  Realm Brew Hex Map Editor",
                 bg=PANEL_BG, fg=ACCENT,
                 font=("Helvetica", 15, "bold")).pack(side=tk.LEFT, padx=14)

        def tb(text, cmd):
            b = tk.Button(topbar, text=text, command=cmd,
                          bg=BTN_BG, fg=BTN_FG,
                          activebackground=BTN_HOVER_BG, activeforeground=BTN_FG,
                          relief=tk.RAISED, bd=1, padx=10, pady=5,
                          font=("Helvetica", 12), cursor="hand2")
            b.pack(side=tk.LEFT, padx=3, pady=10)
            return b

        tb("📂 Open Folder", self._prompt_folder)
        tb("🗋 New Map",     self._new_map)
        tb("💾 Save",        self._save_map)
        tb("📂 Load Map",    self._load_map)
        tk.Frame(topbar, bg=PANEL_BG, width=20).pack(side=tk.LEFT)
        self.btn_tile    = tb("🧱 Place Tile",    lambda: self._set_mode("place_tile"))
        self.btn_overlay = tb("🎭 Place Overlay", lambda: self._set_mode("place_overlay"))
        self.btn_view    = tb("🎛 Controls",      lambda: self._set_mode("view"))

        # Main area
        main = tk.Frame(self.root, bg=BG)
        main.pack(fill=tk.BOTH, expand=True)

        self.canvas = tk.Canvas(main, bg=BG, highlightthickness=0, cursor="crosshair")
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.sidebar = tk.Frame(main, bg=PANEL_BG, width=SIDEBAR_W)
        self.sidebar.pack(side=tk.RIGHT, fill=tk.Y)
        self.sidebar.pack_propagate(False)

        self.status_var = tk.StringVar(value="Open your Realm Brew bundle folder to begin")
        tk.Label(self.root, textvariable=self.status_var,
                 bg=PANEL_BG, fg=TEXT_DIM,
                 font=("Helvetica", 11), anchor=tk.W, padx=10
                 ).pack(side=tk.BOTTOM, fill=tk.X)

        # Bindings
        c = self.canvas
        c.bind("<Motion>",          self._on_motion)
        c.bind("<Button-1>",        self._on_click)
        c.bind("<ButtonRelease-1>", self._on_release)
        c.bind("<Button-2>",        self._pan_start)
        c.bind("<B2-Motion>",       self._pan_move)
        c.bind("<ButtonRelease-2>", self._pan_end)
        c.bind("<Button-3>",        self._pan_start)
        c.bind("<B3-Motion>",       self._pan_move)
        c.bind("<ButtonRelease-3>", self._pan_end)
        c.bind("<MouseWheel>",      self._on_zoom)
        c.bind("<Button-4>",        lambda e: self._zoom(1, e))
        c.bind("<Button-5>",        lambda e: self._zoom(-1, e))

        self.root.bind("<Escape>",       lambda e: self._escape())
        self.root.bind("r",              lambda e: self._rotate_tile(1))
        self.root.bind("R",              lambda e: self._rotate_tile(1))
        self.root.bind("<Right>",        lambda e: self._rotate_tile(1))
        self.root.bind("<Left>",         lambda e: self._rotate_tile(-1))
        self.root.bind("<Delete>",       lambda e: self._delete_action())
        self.root.bind("<BackSpace>",    lambda e: self._delete_action())
        self.root.bind("<bracketright>", lambda e: self._rotate_overlay(15))
        self.root.bind("<bracketleft>",  lambda e: self._rotate_overlay(-15))
        self.root.bind("<equal>",        lambda e: self._scale_overlay(0.1))
        self.root.bind("<minus>",        lambda e: self._scale_overlay(-0.1))
        self.root.bind("<Control-s>",    lambda e: self._save_map())
        self.root.bind("<Control-l>",    lambda e: self._load_map())
        self.root.bind("<Control-n>",    lambda e: self._new_map())
        self.root.bind("<Control-o>",    lambda e: self._prompt_folder())
        self.root.bind("<Configure>",    lambda e: self._redraw())
        self._redraw()

    # ── Mode ──────────────────────────────────────────────────────────────────

    def _set_mode(self, mode):
        self.mode = mode
        self.selected_hex = self.selected_ov_idx = None
        msgs = {
            "view":          "View  •  Right-click drag to pan  •  Scroll to zoom",
            "place_tile":    "Place Tile  •  Pick a tile below  •  Click hex to place  •  R / ← → to rotate  •  ESC to cancel",
            "place_overlay": "Place Overlay  •  Pick overlay below  •  Click hex to place  •  Drag placed overlays to move  •  [ ] rotate  •  –/+ scale  •  ESC to cancel",
        }
        self.status_var.set(msgs.get(mode, ""))
        for btn, m in [(self.btn_tile, "place_tile"),
                       (self.btn_overlay, "place_overlay"),
                       (self.btn_view, "view")]:
            btn.config(bg=BTN_ACTIVE_BG if mode == m else BTN_BG,
                       fg=BTN_ACTIVE_FG if mode == m else BTN_FG)
        self._rebuild_sidebar()
        self._redraw()

    def _escape(self):
        if self.selected_ov_idx is not None:
            self.selected_ov_idx = None
            self._rebuild_sidebar()
            self._redraw()
        else:
            self._set_mode("view")

    # ── File / folder ─────────────────────────────────────────────────────────

    def _prompt_folder(self):
        folder = filedialog.askdirectory(title="Select Realm Brew Complete Bundle folder")
        if not folder:
            return
        ok = self.library.load(folder)
        if ok:
            cats  = list(self.library.categories.keys())
            ocats = list(self.library.overlay_categories.keys())
            self.sel_category    = cats[0]  if cats  else None
            self.sel_ov_category = ocats[0] if ocats else None
            self.sel_tile_idx = self.sel_overlay_idx = None
            n_ov = sum(len(v) for v in self.library.overlay_categories.values())
            self.status_var.set(
                f"Loaded — Tiles: {', '.join(cats)}   "
                f"Overlays: {', '.join(ocats)}   ({n_ov} overlay images total)")
        else:
            messagebox.showwarning("Nothing found",
                "No tiles or overlays found.\n"
                "Select the top-level 'Realm Brew - Complete Bundle' folder.")
        self._rebuild_sidebar()
        self._redraw()

    def _new_map(self):
        if messagebox.askyesno("New Map", "Start fresh? Unsaved changes will be lost."):
            self.hex_map = HexMap()
            self.selected_hex = self.selected_ov_idx = None
            self.status_var.set("New map created")
            self._redraw()

    def _save_map(self):
        path = self.hex_map.filepath or filedialog.asksaveasfilename(
            title="Save Map", defaultextension=".hexmap",
            filetypes=[("Hex Map", "*.hexmap"), ("All", "*.*")])
        if path:
            try:
                self.hex_map.save(path)
                self.status_var.set(f"Saved: {path}")
            except Exception as e:
                messagebox.showerror("Save error", str(e))

    def _load_map(self):
        path = filedialog.askopenfilename(
            title="Load Map", filetypes=[("Hex Map", "*.hexmap"), ("All", "*.*")])
        if path:
            try:
                self.hex_map.load(path)
                self.status_var.set(f"Loaded: {path}")
                self._redraw()
            except Exception as e:
                messagebox.showerror("Load error", str(e))

    # ── Canvas events ─────────────────────────────────────────────────────────

    def _hex_screen(self, col, row):
        hx, hy = hex_to_pixel(col, row, self.hex_size)
        return self.cam_x + hx, self.cam_y + hy

    def _to_hex(self, ex, ey):
        return pixel_to_hex(ex - self.cam_x, ey - self.cam_y, self.hex_size)

    def _on_motion(self, event):
        self.hovered_hex = self._to_hex(event.x, event.y)
        if self._drag_ov_idx is not None:
            ov = self.hex_map.overlays[self._drag_ov_idx]
            hx, hy = hex_to_pixel(ov.col, ov.row, self.hex_size)
            ov.offset_x = event.x - (self.cam_x + hx) - self._drag_ov_offset[0]
            ov.offset_y = event.y - (self.cam_y + hy) - self._drag_ov_offset[1]
        self._redraw()

    def _on_click(self, event):
        col, row = self._to_hex(event.x, event.y)

        if self.mode == "place_overlay":
            hit = self._overlay_hit(event.x, event.y)
            if hit is not None:
                self.selected_ov_idx = hit
                self._drag_ov_idx    = hit
                ov = self.hex_map.overlays[hit]
                hx, hy = hex_to_pixel(ov.col, ov.row, self.hex_size)
                self._drag_ov_offset = (
                    event.x - (self.cam_x + hx) - ov.offset_x,
                    event.y - (self.cam_y + hy) - ov.offset_y)
                self._rebuild_sidebar()
                self._redraw()
                return
            if self.sel_overlay_idx is not None and self.sel_ov_category:
                ovs = self.library.overlay_categories.get(self.sel_ov_category, [])
                if self.sel_overlay_idx < len(ovs):
                    info = ovs[self.sel_overlay_idx]
                    self.hex_map.overlays.append(PlacedOverlay(col, row, str(info.path)))
                    self.selected_ov_idx = len(self.hex_map.overlays) - 1
                    self.status_var.set(
                        f"Placed '{info.name}'  •  Drag to move  •  [ ] rotate  •  –/+ scale  •  Del to remove")
                    self._rebuild_sidebar()
            self._redraw()
            return

        self.selected_hex = (col, row)
        if self.mode == "place_tile" and self.sel_tile_idx is not None and self.sel_category:
            tiles = self.library.categories.get(self.sel_category, [])
            if self.sel_tile_idx < len(tiles):
                t = tiles[self.sel_tile_idx]
                self.hex_map.tiles[(col, row)] = PlacedTile(
                    col, row, str(t.path), self.sel_category, self.placement_rot)
                self.status_var.set(f"Placed '{t.name}' at ({col},{row})  •  R / ← → to rotate")
        self._rebuild_sidebar()
        self._redraw()

    def _on_release(self, event):
        self._drag_ov_idx = None

    def _overlay_hit(self, ex, ey):
        for i in range(len(self.hex_map.overlays) - 1, -1, -1):
            ov = self.hex_map.overlays[i]
            hx, hy = hex_to_pixel(ov.col, ov.row, self.hex_size)
            cx = self.cam_x + hx + ov.offset_x
            cy = self.cam_y + hy + ov.offset_y
            hw = int(self.hex_size * ov.scale * 1.2)
            if abs(ex - cx) <= hw and abs(ey - cy) <= hw:
                return i
        return None

    def _pan_start(self, event):
        self._pan_start_mouse = (event.x, event.y)
        self._pan_start_cam   = (self.cam_x, self.cam_y)

    def _pan_move(self, event):
        if self._pan_start_mouse:
            self.cam_x = self._pan_start_cam[0] + event.x - self._pan_start_mouse[0]
            self.cam_y = self._pan_start_cam[1] + event.y - self._pan_start_mouse[1]
            self._redraw()

    def _pan_end(self, event):
        self._pan_start_mouse = None

    def _on_zoom(self, event):
        self._zoom(1 if event.delta > 0 else -1, event)

    def _zoom(self, direction, event):
        old = self.hex_size
        self.hex_size = max(MIN_HEX_SIZE, min(MAX_HEX_SIZE, self.hex_size + direction * 5))
        scale = self.hex_size / old
        self.cam_x = event.x - scale * (event.x - self.cam_x)
        self.cam_y = event.y - scale * (event.y - self.cam_y)
        self._redraw()

    # ── Actions ───────────────────────────────────────────────────────────────

    def _rotate_tile(self, delta):
        if self.mode != "place_tile":
            return
        self.placement_rot = (self.placement_rot + delta) % ROTATIONS
        if self.selected_hex and self.selected_hex in self.hex_map.tiles:
            self.hex_map.tiles[self.selected_hex].rotation = self.placement_rot
        self._rebuild_sidebar()
        self._redraw()

    def _delete_action(self):
        if self.mode == "place_overlay" and self.selected_ov_idx is not None:
            self._delete_overlay(self.selected_ov_idx)
        elif self.selected_hex and self.selected_hex in self.hex_map.tiles:
            self.hex_map.tiles.pop(self.selected_hex)
            self.status_var.set("Tile removed")
            self._rebuild_sidebar()
            self._redraw()

    def _rotate_overlay(self, delta):
        if self.selected_ov_idx is not None and self.selected_ov_idx < len(self.hex_map.overlays):
            ov = self.hex_map.overlays[self.selected_ov_idx]
            ov.rotation = (ov.rotation + delta) % 360
            self._rebuild_sidebar()
            self._redraw()

    def _scale_overlay(self, delta):
        if self.selected_ov_idx is not None and self.selected_ov_idx < len(self.hex_map.overlays):
            ov = self.hex_map.overlays[self.selected_ov_idx]
            ov.scale = round(max(0.1, min(5.0, ov.scale + delta)), 2)
            self._rebuild_sidebar()
            self._redraw()

    def _delete_overlay(self, idx):
        if 0 <= idx < len(self.hex_map.overlays):
            self.hex_map.overlays.pop(idx)
            self.selected_ov_idx = None
            self.status_var.set("Overlay removed")
            self._rebuild_sidebar()
            self._redraw()

    # ── Drawing ───────────────────────────────────────────────────────────────

    def _redraw(self):
        c = self.canvas
        c.delete("all")
        W, H = c.winfo_width(), c.winfo_height()
        if W < 2 or H < 2:
            return
        self._photo_refs = []

        pad = 2
        tl = pixel_to_hex(-self.cam_x - self.hex_size, -self.cam_y - self.hex_size, self.hex_size)
        br = pixel_to_hex(-self.cam_x + W + self.hex_size, -self.cam_y + H + self.hex_size, self.hex_size)
        cols = range(tl[0] - pad, br[0] + pad + 1)
        rows = range(tl[1] - pad, br[1] + pad + 1)

        for col in cols:
            for row in rows:
                if (col, row) in self.hex_map.tiles:
                    self._draw_tile_image(col, row, self.hex_map.tiles[(col, row)])

        for col in cols:
            for row in rows:
                self._draw_hex_cell(col, row)

        if self.mode == "place_tile" and self.hovered_hex and self.sel_tile_idx is not None:
            self._draw_tile_ghost(*self.hovered_hex)

        for i, ov in enumerate(self.hex_map.overlays):
            self._draw_overlay(ov, selected=(i == self.selected_ov_idx))

    def _draw_tile_image(self, col, row, tile):
        sx, sy = self._hex_screen(col, row)
        try:
            p = self.library.cache.get_tile_photo(tile.path, self.hex_size, tile.rotation)
            self._photo_refs.append(p)
            self.canvas.create_image(sx, sy, image=p, anchor=tk.CENTER)
        except Exception:
            pass

    def _draw_hex_cell(self, col, row):
        sx, sy  = self._hex_screen(col, row)
        pts     = hex_corners(sx, sy, self.hex_size)
        key     = (col, row)
        is_hov  = (self.hovered_hex == key)
        is_sel  = (self.selected_hex == key)
        has     = key in self.hex_map.tiles
        outline = GRID_SEL if is_sel else GRID_HOVER if is_hov else GRID_COL
        width   = 3 if is_sel else 2 if is_hov else 1
        self.canvas.create_polygon(pts, outline=outline,
                                   fill="" if has else "#282c3a", width=width)
        if self.hex_size >= 50:
            self.canvas.create_text(sx, sy, text=f"{col},{row}",
                                    fill=GRID_COL, font=("Helvetica", 9))

    def _draw_tile_ghost(self, col, row):
        tiles = self.library.categories.get(self.sel_category, [])
        if not tiles or self.sel_tile_idx >= len(tiles):
            return
        sx, sy = self._hex_screen(col, row)
        try:
            p = self.library.cache.get_tile_photo(
                str(tiles[self.sel_tile_idx].path), self.hex_size, self.placement_rot)
            self._photo_refs.append(p)
            self.canvas.create_image(sx, sy, image=p, anchor=tk.CENTER)
            pts = hex_corners(sx, sy, self.hex_size)
            self.canvas.create_polygon(pts, fill="#6480ff", outline="", stipple="gray50")
        except Exception:
            pass

    def _draw_overlay(self, ov, selected=False):
        hx, hy = hex_to_pixel(ov.col, ov.row, self.hex_size)
        cx = int(self.cam_x + hx + ov.offset_x)
        cy = int(self.cam_y + hy + ov.offset_y)
        try:
            p = self.library.cache.get_overlay_photo(
                ov.path, self.hex_size, ov.scale, ov.rotation)
            self._photo_refs.append(p)
            self.canvas.create_image(cx, cy, image=p, anchor=tk.CENTER)
            if selected:
                hw, hh = p.width() // 2 + 4, p.height() // 2 + 4
                self.canvas.create_rectangle(
                    cx - hw, cy - hh, cx + hw, cy + hh,
                    outline=GRID_SEL_OV, width=2, dash=(6, 3))
        except Exception:
            pass

    # ── Sidebar ───────────────────────────────────────────────────────────────

    def _rebuild_sidebar(self):
        for w in self.sidebar.winfo_children():
            w.destroy()
        self._thumb_refs = []
        {"place_tile":    self._build_tile_sidebar,
         "place_overlay": self._build_overlay_sidebar
         }.get(self.mode, self._build_view_sidebar)()

    def _lbl(self, parent, text, fg=TEXT_DIM, size=9, bold=False):
        tk.Label(parent, text=text, bg=PANEL_BG, fg=fg,
                 font=("Helvetica", size, "bold" if bold else "normal"),
                 wraplength=SIDEBAR_W - 20, justify=tk.LEFT
                 ).pack(anchor=tk.W, padx=10, pady=(6, 2))

    def _divider(self, parent):
        tk.Frame(parent, bg=PANEL_BORDER, height=1).pack(fill=tk.X, padx=8, pady=4)

    def _btn(self, parent, text, cmd, style="normal", **pack_kw):
        styles = {
            "normal":  (BTN_BG,     BTN_FG,     BTN_HOVER_BG),
            "active":  (BTN_ACTIVE_BG, BTN_ACTIVE_FG, BTN_HOVER_BG),
            "danger":  (BTN_RED_BG, BTN_RED_FG, "#f5b0b0"),
            "success": (BTN_GRN_BG, BTN_GRN_FG, "#b0e0b0"),
        }
        bg, fg, abg = styles.get(style, styles["normal"])
        b = tk.Button(parent, text=text, command=cmd,
                      bg=bg, fg=fg, activebackground=abg, activeforeground=fg,
                      relief=tk.RAISED, bd=1, padx=8, pady=5,
                      font=("Helvetica", 11), cursor="hand2")
        b.pack(**pack_kw)
        return b

    def _category_tabs(self, parent, cats, selected, on_select):
        """Horizontally scrollable row of category buttons."""
        outer = tk.Frame(parent, bg=PANEL_BG)
        outer.pack(fill=tk.X, padx=8, pady=2)

        # Scrollable canvas for the buttons
        hsb = tk.Scrollbar(outer, orient=tk.HORIZONTAL)
        hsb.pack(side=tk.BOTTOM, fill=tk.X)

        tc = tk.Canvas(outer, bg=PANEL_BG, highlightthickness=0,
                       height=40, xscrollcommand=hsb.set)
        tc.pack(side=tk.TOP, fill=tk.X)
        hsb.config(command=tc.xview)

        inner = tk.Frame(tc, bg=PANEL_BG)
        tc.create_window((0, 0), window=inner, anchor=tk.NW)

        for cat in cats:
            sel = (cat == selected)
            tk.Button(inner, text=cat,
                      bg=BTN_ACTIVE_BG if sel else BTN_BG,
                      fg=BTN_ACTIVE_FG if sel else BTN_FG,
                      activebackground=BTN_HOVER_BG,
                      relief=tk.RAISED, bd=1, padx=6, pady=4,
                      font=("Helvetica", 10), cursor="hand2",
                      command=lambda c=cat: on_select(c)
                      ).pack(side=tk.LEFT, padx=2, pady=2)

        inner.update_idletasks()
        tc.config(scrollregion=tc.bbox("all"))
        # Also allow horizontal scroll with shift+mousewheel
        tc.bind("<Shift-MouseWheel>",
                lambda e: tc.xview_scroll(-1 if e.delta > 0 else 1, "units"))

    def _thumb_grid(self, parent, items, selected_idx, on_click):
        wrap = tk.Frame(parent, bg=PANEL_BG)
        wrap.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)
        vsb = tk.Scrollbar(wrap, orient=tk.VERTICAL)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        tc = tk.Canvas(wrap, bg=PANEL_BG, highlightthickness=0, yscrollcommand=vsb.set)
        tc.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.config(command=tc.yview)
        inner = tk.Frame(tc, bg=PANEL_BG)
        tc.create_window((0, 0), window=inner, anchor=tk.NW)
        inner.bind("<Configure>", lambda e: tc.config(scrollregion=tc.bbox("all")))
        tc.bind("<MouseWheel>",
                lambda e: tc.yview_scroll(-1 if e.delta > 0 else 1, "units"))

        cols_n = max(1, (SIDEBAR_W - 32) // (THUMB + 8))
        for i, item in enumerate(items):
            ci, ri = i % cols_n, i // cols_n
            sel    = (i == selected_idx)
            cell   = tk.Frame(inner, bg=BTN_ACTIVE_BG if sel else BTN_BG,
                              bd=2, relief=tk.FLAT)
            cell.grid(row=ri, column=ci, padx=3, pady=3)
            try:
                photo = self.library.cache.get_thumb(str(item.path), THUMB)
                self._thumb_refs.append(photo)
                il = tk.Label(cell, image=photo,
                              bg=BTN_ACTIVE_BG if sel else BTN_BG, cursor="hand2")
                il.pack()
            except Exception:
                il = tk.Label(cell, text="?", bg=BTN_BG, fg=TEXT,
                              width=THUMB // 10, height=3, cursor="hand2")
                il.pack()
            nl = tk.Label(cell, text=item.name[:13],
                          bg=BTN_ACTIVE_BG if sel else BTN_BG,
                          fg=BTN_ACTIVE_FG if sel else BTN_FG,
                          font=("Helvetica", 9))
            nl.pack()
            for w in (cell, il, nl):
                w.bind("<Button-1>", lambda e, idx=i: on_click(idx))

    # ── Tile sidebar ──────────────────────────────────────────────────────────

    def _build_tile_sidebar(self):
        p = self.sidebar
        self._lbl(p, "TILE CATEGORY", bold=True)
        cats = list(self.library.categories.keys())
        self._category_tabs(p, cats, self.sel_category, self._sel_tile_cat)

        self._divider(p)
        self._lbl(p, f"ROTATION  ({self.placement_rot + 1}/6 × 60°)", bold=True)
        row = tk.Frame(p, bg=PANEL_BG)
        row.pack(fill=tk.X, padx=8)
        self._btn(row, "◀  Rotate Left",  lambda: self._rotate_tile(-1),
                  side=tk.LEFT, padx=2)
        self._btn(row, "Rotate Right  ▶", lambda: self._rotate_tile(1),
                  side=tk.LEFT, padx=2)

        self._divider(p)
        self._lbl(p, "SELECT TILE — click thumbnail, then click map to place", bold=True)
        tiles = self.library.categories.get(self.sel_category, [])
        self._thumb_grid(p, tiles, self.sel_tile_idx, self._sel_tile)

        if self.selected_hex and self.selected_hex in self.hex_map.tiles:
            self._divider(p)
            self._btn(p, "✖  Remove Tile at Selected Hex",
                      self._delete_action, style="danger",
                      fill=tk.X, padx=8, pady=4)

    def _sel_tile_cat(self, cat):
        self.sel_category = cat
        self.sel_tile_idx = None
        self._rebuild_sidebar()

    def _sel_tile(self, idx):
        self.sel_tile_idx = idx
        tiles = self.library.categories.get(self.sel_category, [])
        if idx < len(tiles):
            self.status_var.set(
                f"Selected '{tiles[idx].name}'  •  Click a hex to place  •  R / ← → to rotate")
        self._rebuild_sidebar()

    # ── Overlay sidebar ───────────────────────────────────────────────────────

    def _build_overlay_sidebar(self):
        p = self.sidebar
        self._lbl(p, "OVERLAY CATEGORY", bold=True)
        ocats = list(self.library.overlay_categories.keys())
        if not ocats:
            self._lbl(p, "No overlays found. Add PNGs to a folder with 'Overlays' in its name.")
            return
        self._category_tabs(p, ocats, self.sel_ov_category, self._sel_ov_cat)

        self._divider(p)
        self._lbl(p, "SELECT OVERLAY — click thumbnail, then click map to place", bold=True)
        ovs = self.library.overlay_categories.get(self.sel_ov_category, [])
        self._thumb_grid(p, ovs, self.sel_overlay_idx, self._sel_overlay)

        if self.selected_ov_idx is not None and self.selected_ov_idx < len(self.hex_map.overlays):
            ov = self.hex_map.overlays[self.selected_ov_idx]
            self._divider(p)
            self._lbl(p, f"SELECTED OVERLAY  —  rotation {ov.rotation}°  •  scale {ov.scale:.2f}×", bold=True)

            row1 = tk.Frame(p, bg=PANEL_BG)
            row1.pack(fill=tk.X, padx=8, pady=2)
            self._btn(row1, "↺ –15°", lambda: self._rotate_overlay(-15), side=tk.LEFT, padx=2)
            self._btn(row1, "↻ +15°", lambda: self._rotate_overlay(15),  side=tk.LEFT, padx=2)

            row2 = tk.Frame(p, bg=PANEL_BG)
            row2.pack(fill=tk.X, padx=8, pady=2)
            self._btn(row2, "–  Smaller", lambda: self._scale_overlay(-0.1), side=tk.LEFT, padx=2)
            self._btn(row2, "+  Larger",  lambda: self._scale_overlay(0.1),  side=tk.LEFT, padx=2)

            self._btn(p, "✖  Delete This Overlay",
                      lambda: self._delete_overlay(self.selected_ov_idx),
                      style="danger", fill=tk.X, padx=8, pady=4)
            self._lbl(p, "Keyboard: [ ]  rotate  •  – +  scale  •  Del  remove")

    def _sel_ov_cat(self, cat):
        self.sel_ov_category = cat
        self.sel_overlay_idx = None
        self._rebuild_sidebar()

    def _sel_overlay(self, idx):
        self.sel_overlay_idx = idx
        ovs = self.library.overlay_categories.get(self.sel_ov_category, [])
        if idx < len(ovs):
            self.status_var.set(
                f"Selected '{ovs[idx].name}'  •  Click a hex to place it")
        self._rebuild_sidebar()

    # ── View sidebar ──────────────────────────────────────────────────────────

    def _build_view_sidebar(self):
        p = self.sidebar
        self._lbl(p, "MAP INFO", fg=ACCENT, size=13, bold=True)

        n_ov = sum(len(v) for v in self.library.overlay_categories.values())
        for label, val in [
            ("Tiles placed:",     str(len(self.hex_map.tiles))),
            ("Overlays placed:",  str(len(self.hex_map.overlays))),
            ("Tile sets loaded:", str(len(self.library.categories))),
            ("Overlay sets:",     str(len(self.library.overlay_categories))),
            ("Overlay images:",   str(n_ov)),
        ]:
            row = tk.Frame(p, bg=PANEL_BG)
            row.pack(fill=tk.X, padx=10, pady=1)
            tk.Label(row, text=label, bg=PANEL_BG, fg=TEXT_DIM,
                     font=("Helvetica", 11)).pack(side=tk.LEFT)
            tk.Label(row, text=val, bg=PANEL_BG, fg=TEXT,
                     font=("Helvetica", 11, "bold")).pack(side=tk.LEFT, padx=4)

        self._divider(p)
        self._lbl(p, "KEYBOARD SHORTCUTS", fg=ACCENT, size=11, bold=True)

        shortcuts = [
            ("R / → / ←",   "Rotate tile"),
            ("[ / ]",        "Rotate overlay ±15°"),
            ("– / +",        "Scale overlay smaller/larger"),
            ("Del / ⌫",     "Remove tile or overlay"),
            ("Scroll",        "Zoom"),
            ("Right-drag",    "Pan"),
            ("ESC",           "Deselect / View mode"),
            ("Ctrl+S",        "Save"),
            ("Ctrl+L",        "Load"),
            ("Ctrl+N",        "New map"),
            ("Ctrl+O",        "Open folder"),
        ]
        for key, desc in shortcuts:
            row = tk.Frame(p, bg=PANEL_BG)
            row.pack(fill=tk.X, padx=10, pady=1)
            tk.Label(row, text=key, bg=PANEL_BG, fg=ACCENT,
                     font=("Helvetica", 10, "bold"), width=14,
                     anchor=tk.W).pack(side=tk.LEFT)
            tk.Label(row, text=desc, bg=PANEL_BG, fg=TEXT,
                     font=("Helvetica", 10)).pack(side=tk.LEFT)

        if self.selected_hex:
            self._divider(p)
            col, row = self.selected_hex
            self._lbl(p, f"Selected hex: ({col}, {row})", fg=ACCENT, size=11, bold=True)
            if self.selected_hex in self.hex_map.tiles:
                t = self.hex_map.tiles[self.selected_hex]
                for line in [Path(t.path).stem,
                              f"Category: {t.category}",
                              f"Rotation: {t.rotation} × 60°"]:
                    tk.Label(p, text=f"  {line}", bg=PANEL_BG, fg=TEXT,
                             font=("Helvetica", 10)).pack(anchor=tk.W, padx=10)
            else:
                tk.Label(p, text="  (empty hex)", bg=PANEL_BG, fg=TEXT_DIM,
                         font=("Helvetica", 10)).pack(anchor=tk.W, padx=10)


# ─── Entry point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    try:
        from PIL import Image, ImageTk
    except ImportError:
        import subprocess, sys
        print("Installing Pillow...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pillow"])
        from PIL import Image, ImageTk

    root = tk.Tk()
    App(root)
    root.mainloop()
