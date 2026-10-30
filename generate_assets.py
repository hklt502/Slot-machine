#!/usr/bin/env python3
import struct, math, os

def rgb888_to_rgb565(r, g, b):
    return ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)

def rgb565_to_rgb888(c):
    r = ((c >> 11) & 0x1F) * 255 // 31
    g = ((c >> 5) & 0x3F) * 255 // 63
    b = (c & 0x1F) * 255 // 31
    return (r, g, b)

def save_bmp(filename, width, height, pixels):
    row_pad = (4 - (width * 3) % 4) % 4
    image_size = (width * 3 + row_pad) * height
    file_size = 54 + image_size
    header = struct.pack("<2sIHHI", b"BM", file_size, 0, 0, 54)
    info = struct.pack("<IIIHHIIIIII", 40, width, height, 1, 24, 0, image_size, 2835, 2835, 0, 0)
    with open(filename, "wb") as f:
        f.write(header)
        f.write(info)
        for y in range(height - 1, -1, -1):
            for x in range(width):
                r, g, b = pixels[y][x]
                f.write(bytes([b, g, r]))
            f.write(b"\x00" * row_pad)

# 1. Generate 120-line metallic cylinder gradient matching sample image
# In the sample image:
# y=0..12: Dark shadow at cylinder top edge (almost black/brown: 20..60)
# y=13..38: Sharp metallic rise up to brilliant specular highlight (255, 248, 190)
# y=39..75: Warm rich gold center (235, 185, 80 to 248, 215, 120)
# y=76..100: Secondary metallic specular reflection band (250, 230, 160)
# y=101..119: Dark shadow at cylinder bottom edge (60..20)
reel_gradient_565 = []
for y in range(120):
    t = y / 119.0
    # Base curve: cosine shadow at extremities
    edge_shadow = math.sin(t * math.pi) ** 0.35 # 0 at edges, 1 in middle
    # Specular band 1 at t=0.22 (width ~0.12)
    spec1 = math.exp(-((t - 0.22) / 0.08) ** 2)
    # Specular band 2 at t=0.78 (width ~0.12)
    spec2 = math.exp(-((t - 0.78) / 0.08) ** 2)
    # Center warm gold
    mid_gold = math.exp(-((t - 0.50) / 0.22) ** 2)

    r = int(35 + 175 * edge_shadow + 45 * spec1 + 40 * spec2 + 5 * mid_gold)
    g = int(22 + 155 * edge_shadow + 75 * spec1 + 60 * spec2 + 10 * mid_gold)
    b = int(10 + 40 * edge_shadow + 140 * spec1 + 100 * spec2 + 5 * mid_gold)
    r = min(255, max(0, r))
    g = min(255, max(0, g))
    b = min(255, max(0, b))
    reel_gradient_565.append(rgb888_to_rgb565(r, g, b))

print("Generated 120-line gradient")

# 2. Design 10 distinct 36x36 slot symbols
# Every symbol has:
# 16-color palette (Color 0 = Transparent / Reel Background)
# Color 1 = Cream / Pale Gold Outer Halo (e.g. 0xFFFE or 0xFFF5)
# Color 2 = Jet Black / Deep Dark Brown Outline (0x1040 or 0x0000)
# Colors 3..15 = Rich shaded body gradients + specular highlights
SYM_W = 36
SYM_H = 36

symbols = []

# Helper to build symbol
class SymbolBuilder:
    def __init__(self, name, palette_565):
        self.name = name
        self.pal = palette_565 # 16 colors (uint16_t)
        self.grid = [[0 for _ in range(SYM_W)] for _ in range(SYM_H)]
    
    def set(self, x, y, col_idx):
        if 0 <= x < SYM_W and 0 <= y < SYM_H:
            self.grid[y][x] = col_idx
            
    def fill_rect(self, x0, y0, w, h, col_idx):
        for y in range(y0, y0 + h):
            for x in range(x0, x0 + w):
                self.set(x, y, col_idx)

    def draw_circle(self, cx, cy, radius, col_idx):
        for y in range(int(cy - radius - 1), int(cy + radius + 2)):
            for x in range(int(cx - radius - 1), int(cx + radius + 2)):
                if (x - cx)**2 + (y - cy)**2 <= radius**2:
                    self.set(x, y, col_idx)

    def add_outline_and_glow(self, inside_color_range, outline_col=2, glow_col=1):
        # find border pixels of inside
        has_body = [[(self.grid[y][x] in inside_color_range) for x in range(SYM_W)] for y in range(SYM_H)]
        # Outline: 1px around body
        outline_mask = [[False for _ in range(SYM_W)] for _ in range(SYM_H)]
        for y in range(SYM_H):
            for x in range(SYM_W):
                if not has_body[y][x]:
                    # check 8 neighbors
                    is_neighbor = False
                    for dy in (-1, 0, 1):
                        for dx in (-1, 0, 1):
                            ny, nx = y + dy, x + dx
                            if 0 <= ny < SYM_H and 0 <= nx < SYM_W and has_body[ny][nx]:
                                is_neighbor = True
                                break
                        if is_neighbor: break
                    if is_neighbor:
                        outline_mask[y][x] = True
        
        # Glow: 1px around outline
        glow_mask = [[False for _ in range(SYM_W)] for _ in range(SYM_H)]
        for y in range(SYM_H):
            for x in range(SYM_W):
                if not has_body[y][x] and not outline_mask[y][x]:
                    is_neighbor = False
                    for dy in (-1, 0, 1):
                        for dx in (-1, 0, 1):
                            ny, nx = y + dy, x + dx
                            if 0 <= ny < SYM_H and 0 <= nx < SYM_W and outline_mask[ny][nx]:
                                is_neighbor = True
                                break
                        if is_neighbor: break
                    if is_neighbor:
                        glow_mask[y][x] = True

        for y in range(SYM_H):
            for x in range(SYM_W):
                if glow_mask[y][x]:
                    self.grid[y][x] = glow_col
                elif outline_mask[y][x]:
                    self.grid[y][x] = outline_col

# SYMBOL 0: DOLLAR ($)
pal_dollar = [
    0x0000, # 0: Transparent
    0xFFFD, # 1: Cream Halo (255, 255, 235)
    0x1840, # 2: Black Stroke (20, 10, 0)
    0x8260, # 3: Deep Bronze Shadow (130, 75, 0)
    0xA3A0, # 4: Warm Bronze (165, 115, 0)
    0xC4A0, # 5: Dark Gold (195, 145, 0)
    0xDD40, # 6: Mid Gold (220, 170, 0)
    0xFE40, # 7: Bright Gold (255, 200, 0)
    0xFEC0, # 8: Radiant Yellow Gold (255, 215, 0)
    0xFF70, # 9: Pale Gold Highlight (255, 235, 130)
    0xFFFF, # 10: White Specular Shine (255, 255, 255)
    0x6180, # 11: Dark Shading
    0x0000, 0x0000, 0x0000, 0x0000
]
s_dollar = SymbolBuilder("dollar", pal_dollar)
# Vertical bar in center
for y in range(2, 34):
    for x in range(16, 20):
        s_dollar.set(x, y, 7)

# Top loop: center (18, 12)
for y in range(5, 19):
    for x in range(8, 29):
        dx = (x - 18) / 9.5
        dy = (y - 12) / 6.5
        d = dx*dx + dy*dy
        if 0.35 <= d <= 1.05:
            if dy <= 0 or dx <= 0.1:
                s_dollar.set(x, y, 8 if dy < -0.3 else 7)

# Middle stroke connecting top left to bottom right
for t in range(16):
    cx = 11 + t * 0.95
    cy = 13 + t * 0.75
    for dy in range(-2, 3):
        for dx in range(-2, 3):
            if dx*dx + dy*dy <= 4:
                s_dollar.set(int(cy + dy), int(cx + dx), 7)

# Bottom loop: center (18, 23)
for y in range(17, 31):
    for x in range(7, 28):
        dx = (x - 18) / 9.5
        dy = (y - 23) / 6.5
        d = dx*dx + dy*dy
        if 0.35 <= d <= 1.05:
            if dy >= 0 or dx >= -0.1:
                s_dollar.set(x, y, 6 if dy > 0.3 else 7)

# Upper shine
for y in range(5, 10):
    for x in range(11, 23):
        if s_dollar.grid[y][x] != 0:
            s_dollar.set(x, y, 10 if y < 8 else 9)

s_dollar.add_outline_and_glow(range(3, 12))
symbols.append(s_dollar)

# SYMBOL 1: BAR
pal_bar = [
    0x0000, # 0: Trans
    0xFFD4, # 1: Cream Halo
    0x1840, # 2: Black Stroke
    0xBA00, # 3: Red Outer Border (185, 30, 0)
    0xF9A0, # 4: Bright Red Trim (250, 50, 0)
    0xDEFB, # 5: Light Silver (220, 220, 220)
    0xFFFF, # 6: White Silver Highlight
    0x9CD3, # 7: Mid Gray (155, 155, 155)
    0x630C, # 8: Dark Gray (100, 100, 100)
    0x18C3, # 9: Deep Charcoal Letter (25, 25, 25)
    0x0000, 0x0000, 0x0000, 0x0000, 0x0000, 0x0000
]
s_bar = SymbolBuilder("bar", pal_bar)
# Double BAR plaque: x=4..31 (w=28), y=6..29 (h=24)
s_bar.fill_rect(4, 6, 28, 24, 4)
s_bar.fill_rect(5, 7, 26, 22, 3)
# Top plaque: y=8..16
s_bar.fill_rect(6, 8, 24, 9, 5)
for x in range(6, 30):
    s_bar.set(x, 8, 6) # highlight top edge
# Red separator line: y=17
s_bar.fill_rect(5, 17, 26, 2, 4)
# Bottom plaque: y=19..27
s_bar.fill_rect(6, 19, 24, 9, 5)
for x in range(6, 30):
    s_bar.set(x, 19, 6)

# Text "BAR" on top (y=9..15)
# B: x=8..12
s_bar.fill_rect(8, 10, 2, 6, 9)
s_bar.fill_rect(10, 10, 3, 1, 9)
s_bar.fill_rect(10, 12, 3, 1, 9)
s_bar.fill_rect(10, 15, 3, 1, 9)
s_bar.set(13, 11, 9); s_bar.set(13, 14, 9)
# A: x=16..20
s_bar.fill_rect(16, 11, 1, 5, 9)
s_bar.fill_rect(20, 11, 1, 5, 9)
s_bar.fill_rect(17, 10, 3, 1, 9)
s_bar.fill_rect(17, 13, 3, 1, 9)
# R: x=24..28
s_bar.fill_rect(24, 10, 2, 6, 9)
s_bar.fill_rect(26, 10, 2, 1, 9)
s_bar.fill_rect(26, 12, 2, 1, 9)
s_bar.set(28, 11, 9)
s_bar.fill_rect(27, 13, 2, 3, 9)

# Text "BAR" on bottom (y=20..26)
# B: x=8..12
s_bar.fill_rect(8, 21, 2, 6, 9)
s_bar.fill_rect(10, 21, 3, 1, 9)
s_bar.fill_rect(10, 23, 3, 1, 9)
s_bar.fill_rect(10, 26, 3, 1, 9)
s_bar.set(13, 22, 9); s_bar.set(13, 25, 9)
# A: x=16..20
s_bar.fill_rect(16, 22, 1, 5, 9)
s_bar.fill_rect(20, 22, 1, 5, 9)
s_bar.fill_rect(17, 21, 3, 1, 9)
s_bar.fill_rect(17, 24, 3, 1, 9)
# R: x=24..28
s_bar.fill_rect(24, 21, 2, 6, 9)
s_bar.fill_rect(26, 21, 2, 1, 9)
s_bar.fill_rect(26, 23, 2, 1, 9)
s_bar.set(28, 22, 9)
s_bar.fill_rect(27, 24, 2, 3, 9)

s_bar.add_outline_and_glow(range(3, 10))
symbols.append(s_bar)

# SYMBOL 2: CHERRY
pal_cherry = [
    0x0000, # 0: Trans
    0xFFF6, # 1: Cream Halo
    0x1800, # 2: Dark Stroke
    0x7800, # 3: Deep Dark Red Shadow (120, 0, 0)
    0xB841, # 4: Rich Crimson Red (185, 10, 10)
    0xE943, # 5: Bright Cherry Red (235, 30, 25)
    0xFBA7, # 6: Specular Red Highlight (250, 115, 55)
    0xFFFF, # 7: Pure White Specular Dot
    0x6280, # 8: Wood Stem Brown (100, 50, 0)
    0x8BC0, # 9: Light Stem Brown (140, 95, 0)
    0x1B82, # 10: Dark Green Leaf (25, 90, 15)
    0x3CE5, # 11: Lush Green Leaf (60, 155, 40)
    0x7E49, # 12: Light Green Leaf Highlight (125, 200, 75)
    0x0000, 0x0000, 0x0000, 0x0000
]
s_cherry = SymbolBuilder("cherry", pal_cherry)
# Cherry 1 (left): cx=12, cy=24, r=7
s_cherry.draw_circle(12, 24, 7, 4)
s_cherry.draw_circle(12, 24, 5, 5)
s_cherry.fill_rect(10, 21, 3, 3, 6)
s_cherry.set(11, 22, 7)

# Cherry 2 (right): cx=22, cy=22, r=8
s_cherry.draw_circle(22, 22, 8, 3)
s_cherry.draw_circle(22, 22, 6.5, 4)
s_cherry.draw_circle(21, 21, 5, 5)
s_cherry.fill_rect(19, 18, 4, 3, 6)
s_cherry.set(20, 19, 7)

# Stems: curved to top right cx=19, cy=6
for t_step in range(18):
    st = t_step / 17.0
    # Left stem: from (12, 17) to (19, 7)
    lx = int(12 + (19 - 12) * st + 2 * math.sin(st * math.pi))
    ly = int(17 - 10 * st)
    s_cherry.fill_rect(lx, ly, 2, 1, 9)
    # Right stem: from (22, 14) to (19, 7)
    rx = int(22 - (22 - 19) * st)
    ry = int(14 - 7 * st)
    s_cherry.fill_rect(rx, ry, 2, 1, 8)

# Green leaf at top right: cx=26, cy=9
for ly in range(6, 14):
    for lx in range(19, 32):
        if (lx - 25)**2 / 36.0 + (ly - 9)**2 / 9.0 <= 1.0:
            s_cherry.set(lx, ly, 11)
s_cherry.fill_rect(22, 8, 6, 1, 12)

s_cherry.add_outline_and_glow(range(3, 13))
symbols.append(s_cherry)

# SYMBOL 3: WATERMELON
pal_melon = [
    0x0000, # 0: Trans
    0xFFF6, # 1: Cream Halo
    0x1840, # 2: Black Stroke
    0x1382, # 3: Deep Green Rind (20, 70, 15)
    0x2C84, # 4: Vibrant Green (45, 145, 35)
    0x9609, # 5: Bright Light Green (150, 195, 75)
    0xFFF8, # 6: White Rind Layer (255, 255, 240)
    0xBA03, # 7: Dark Red Pulp (185, 35, 25)
    0xF206, # 8: Bright Crimson Pulp (245, 65, 50)
    0xFB08, # 9: Juicy Red Highlight (250, 100, 65)
    0x1081, # 10: Black Seed (15, 15, 10)
    0x0000, 0x0000, 0x0000, 0x0000, 0x0000, 0x0000
]
s_melon = SymbolBuilder("watermelon", pal_melon)
# Crescent watermelon slice: center (18, 12), outer radius 17, inner radius 10
for y in range(10, 31):
    for x in range(3, 33):
        dx = x - 18
        dy = y - 12
        dist = math.sqrt(dx*dx + dy*dy)
        if 8.5 <= dist <= 17.0 and dy > 0:
            if dist >= 15.2:
                s_melon.set(x, y, 4 if dy < 14 else 3)
            elif dist >= 14.0:
                s_melon.set(x, y, 5)
            elif dist >= 12.8:
                s_melon.set(x, y, 6)
            else:
                s_melon.set(x, y, 8 if dy > 5 else 9)

# Watermelon seeds
seeds = [(12, 19), (18, 22), (24, 19), (15, 21), (21, 21)]
for sx, sy in seeds:
    s_melon.fill_rect(sx, sy, 2, 2, 10)

s_melon.add_outline_and_glow(range(3, 11))
symbols.append(s_melon)

# SYMBOL 4: PLUM
pal_plum = [
    0x0000, # 0: Trans
    0xFFF6, # 1: Cream Halo
    0x1840, # 2: Black Stroke
    0x2886, # 3: Deep Plum Shadow (40, 15, 50)
    0x58EB, # 4: Dark Violet (90, 30, 90)
    0x7A0F, # 5: Royal Purple (125, 40, 125)
    0xA315, # 6: Vivid Purple (165, 60, 170)
    0xD4DD, # 7: Soft Lavender Highlight (210, 155, 220)
    0xFFFF, # 8: Specular Shine Dot
    0x6A41, # 9: Stem Brown
    0x2CA4, # 10: Green Leaf
    0x65A8, # 11: Light Green Leaf
    0x0000, 0x0000, 0x0000, 0x0000
]
s_plum = SymbolBuilder("plum", pal_plum)
# Oval plum body: center (18, 22), rx=11, ry=10
for y in range(11, 33):
    for x in range(6, 30):
        dx = (x - 18) / 11.5
        dy = (y - 22) / 10.5
        if dx*dx + dy*dy <= 1.0:
            if dx < -0.3 and dy < -0.2:
                s_plum.set(x, y, 7)
            elif dx < 0.2:
                s_plum.set(x, y, 6)
            elif dx < 0.6:
                s_plum.set(x, y, 5)
            else:
                s_plum.set(x, y, 4)
# Specular dot
s_plum.fill_rect(13, 17, 3, 3, 8)
# Indentation furrow
for y in range(13, 29):
    s_plum.set(18, y, 4)

# Stem & leaf at top (x=18, y=5..12)
for y in range(7, 13):
    s_plum.set(18, y, 9)
s_plum.fill_rect(19, 6, 7, 4, 10)
s_plum.fill_rect(21, 7, 4, 1, 11)

s_plum.add_outline_and_glow(range(3, 12))
symbols.append(s_plum)

# SYMBOL 5: BELL
pal_bell = [
    0x0000, # 0: Trans
    0xFFF6, # 1: Cream Halo
    0x1840, # 2: Black Stroke
    0x69A0, # 3: Deep Bronze Shadow (105, 55, 0)
    0x9B60, # 4: Dark Gold (155, 110, 0)
    0xC4A0, # 5: Warm Gold (195, 145, 0)
    0xDD40, # 6: Golden Body (220, 170, 0)
    0xFEC0, # 7: Bright Gold (255, 215, 0)
    0xFF74, # 8: Specular Highlight (255, 240, 160)
    0xFFFF, # 9: White Shine
    0x39A0, # 10: Clapper Dark Bronze (60, 30, 0)
    0x0000, 0x0000, 0x0000, 0x0000, 0x0000, 0x0000
]
s_bell = SymbolBuilder("bell", pal_bell)
# Bell hanger at top: x=16..20, y=5..8
s_bell.fill_rect(16, 5, 5, 4, 6)
s_bell.fill_rect(17, 6, 3, 2, 8)
# Bell body: flares outward from top (w=10 at y=9) to skirt (w=26 at y=26)
for y in range(9, 27):
    t = (y - 9) / 17.0
    half_w = 4.0 + 8.5 * (t ** 1.6)
    x0 = int(18 - half_w)
    x1 = int(18 + half_w)
    for x in range(x0, x1 + 1):
        rel_x = (x - x0) / max(1.0, (x1 - x0))
        if rel_x < 0.25:
            s_bell.set(x, y, 8 if rel_x > 0.1 else 7)
        elif rel_x < 0.65:
            s_bell.set(x, y, 7)
        elif rel_x < 0.85:
            s_bell.set(x, y, 5)
        else:
            s_bell.set(x, y, 4)
# Bottom rim: y=26..28, w=28
s_bell.fill_rect(4, 26, 28, 3, 6)
s_bell.fill_rect(6, 26, 8, 2, 8)
s_bell.fill_rect(18, 26, 12, 2, 4)
# Clapper at bottom center: x=16..20, y=29..31
s_bell.fill_rect(16, 29, 5, 3, 10)
s_bell.fill_rect(17, 29, 3, 2, 4)

s_bell.add_outline_and_glow(range(3, 11))
symbols.append(s_bell)

# SYMBOL 6: YS (Arcade Gold/Red Metallic)
pal_ys = [
    0x0000, # 0: Trans
    0xFFF6, # 1: Cream Halo
    0x1840, # 2: Black Stroke
    0x6000, # 3: Deep Maroon (3D shadow)
    0x9800, # 4: Dark Crimson
    0xD000, # 5: Rich Ruby Red
    0xF900, # 6: Vivid Fiery Scarlet
    0xB3A0, # 7: Warm Bronze / Deep Gold
    0xDC60, # 8: Mid Gold
    0xFE40, # 9: Bright Pure Gold
    0xFFE0, # 10: Radiant Yellow Highlight
    0xFFFF, # 11: Pure White Specular Shine
    0xFC68, # 12: Light Peach / Coral Highlight
    0x0000, 0x0000, 0x0000
]
s_ys = SymbolBuilder("ys", pal_ys)

# Letter 'Y':
for y in range(5, 17):
    t = (y - 5) / 11.0
    lx = int(3 + 4.5 * t)
    s_ys.fill_rect(lx, y, 4, 1, 5)

for y in range(5, 17):
    t = (y - 5) / 11.0
    rx = int(13 - 3.5 * t)
    s_ys.fill_rect(rx, y, 4, 1, 5)

s_ys.fill_rect(7, 16, 5, 12, 5)
s_ys.fill_rect(2, 5, 5, 2, 5)   # Top left serif
s_ys.fill_rect(12, 5, 5, 2, 5)  # Top right serif
s_ys.fill_rect(5, 27, 9, 3, 5)  # Bottom base

# Letter 'S':
s_ys.fill_rect(21, 5, 10, 2, 5) # Top bar
s_ys.fill_rect(28, 6, 4, 4, 5)  # Top-right terminal
s_ys.fill_rect(19, 6, 4, 3, 5)  # Top-left corner
s_ys.fill_rect(19, 9, 5, 6, 5)  # Left spine
s_ys.fill_rect(19, 14, 8, 3, 5) # Waist upper
s_ys.fill_rect(22, 16, 8, 3, 5) # Waist lower
s_ys.fill_rect(27, 18, 5, 6, 5) # Right spine
s_ys.fill_rect(19, 23, 4, 4, 5) # Bottom-left terminal
s_ys.fill_rect(28, 24, 4, 3, 5) # Bottom-right corner
s_ys.fill_rect(20, 26, 10, 3, 5)# Bottom bar

# Metallic shading across the letters (Gold top, Red bottom)
for y in range(SYM_H):
    for x in range(SYM_W):
        if s_ys.grid[y][x] == 5:
            if y <= 6:
                s_ys.set(x, y, 11 if (y == 5 and (x % 2 == 0)) else 10)
            elif y <= 10:
                s_ys.set(x, y, 9 if (x % 4 != 0) else 10)
            elif y <= 14:
                s_ys.set(x, y, 8 if (y < 13) else 7)
            elif y <= 18:
                s_ys.set(x, y, 6)
            elif y <= 23:
                s_ys.set(x, y, 5)
            elif y <= 27:
                s_ys.set(x, y, 4)
            else:
                s_ys.set(x, y, 3)

# Extra bevel highlights on left edges and top of letters
for y in range(5, 16):
    t = (y - 5) / 11.0
    lx = int(3 + 4.5 * t)
    if s_ys.grid[y][lx] in range(3, 11):
        s_ys.set(lx, y, 11 if y < 8 else (10 if y < 14 else 12))

for x in range(21, 30):
    s_ys.set(x, 5, 11)

s_ys.set(19, 6, 11)
s_ys.set(20, 6, 10)
s_ys.set(19, 7, 10)

s_ys.add_outline_and_glow(range(3, 13))
symbols.append(s_ys)

# SYMBOL 7: DIAMOND
pal_diamond = [
    0x0000, # 0: Trans
    0xFFF6, # 1: Cream Halo
    0x1840, # 2: Black Stroke
    0x1251, # 3: Deep Navy Facet (15, 75, 140)
    0x23F7, # 4: Sapphire Blue (35, 125, 190)
    0x451C, # 5: Bright Cyan-Blue (65, 160, 225)
    0x6E5F, # 6: Light Cyan (110, 200, 255)
    0xB73F, # 7: Pale Aqua Shimmer (180, 230, 255)
    0xFFFF, # 8: Brilliant White Sparkle
    0x0000, 0x0000, 0x0000, 0x0000, 0x0000, 0x0000, 0x0000
]
s_diamond = SymbolBuilder("diamond", pal_diamond)
# Diamond shape: top crown y=8..15, bottom pavilion y=15..30
# Table (top flat): x=12..24, y=8
# Outer corners: left=(5, 15), right=(31, 15), bottom culet=(18, 30)
for y in range(8, 16):
    t = (y - 8) / 7.0
    x0 = int(12 - 7 * t)
    x1 = int(24 + 7 * t)
    for x in range(x0, x1 + 1):
        if x < 12: s_diamond.set(x, y, 6)
        elif x <= 24: s_diamond.set(x, y, 7 if y < 11 else 8)
        else: s_diamond.set(x, y, 5)

for y in range(16, 31):
    t = (y - 16) / 14.0
    x0 = int(5 + 13 * t)
    x1 = int(31 - 13 * t)
    for x in range(x0, x1 + 1):
        rel = (x - x0) / max(1.0, (x1 - x0))
        if rel < 0.3: s_diamond.set(x, y, 6 if t < 0.5 else 5)
        elif rel < 0.7: s_diamond.set(x, y, 5 if t < 0.5 else 4)
        else: s_diamond.set(x, y, 4 if t < 0.5 else 3)

# Sparkle cross on top table
s_diamond.set(18, 10, 8); s_diamond.set(17, 10, 8); s_diamond.set(19, 10, 8)
s_diamond.set(18, 9, 8); s_diamond.set(18, 11, 8)

s_diamond.add_outline_and_glow(range(3, 9))
symbols.append(s_diamond)

# SYMBOL 8: LEMON
pal_lemon = [
    0x0000, # 0: Trans
    0xFFF6, # 1: Cream Halo
    0x1840, # 2: Black Stroke
    0x8BA0, # 3: Dark Ochre (140, 95, 0)
    0xB4A0, # 4: Warm Gold (180, 150, 0)
    0xDC80, # 5: Vivid Yellow (220, 200, 0)
    0xFEE0, # 6: Bright Lemon Yellow (255, 235, 0)
    0xFF94, # 7: Pale Yellow Highlight (255, 245, 160)
    0xFFFF, # 8: Specular White Shine
    0x4A60, # 9: Stem Brown
    0x2402, # 10: Leaf Green
    0x5486, # 11: Light Leaf Green
    0x0000, 0x0000, 0x0000, 0x0000
]
s_lemon = SymbolBuilder("lemon", pal_lemon)
# Plump oval lemon: center (18, 20), tilted slightly or pointed ends: left (6, 20), right (30, 20)
for y in range(10, 31):
    for x in range(6, 31):
        dx = (x - 18) / 12.0
        dy = (y - 20) / 9.0
        # Lemon shape formula
        d = dx*dx + dy*dy
        if d <= 1.0:
            if dx < -0.2 and dy < -0.2:
                s_lemon.set(x, y, 7)
            elif dx < 0.3:
                s_lemon.set(x, y, 6)
            elif dx < 0.7:
                s_lemon.set(x, y, 5)
            else:
                s_lemon.set(x, y, 4)
# Lemon tips
s_lemon.fill_rect(5, 19, 2, 3, 5)
s_lemon.fill_rect(29, 19, 2, 3, 4)
# Specular shine
s_lemon.fill_rect(13, 15, 4, 2, 8)

# Stem & leaf at top right (x=21..28, y=6..11)
s_lemon.fill_rect(20, 9, 3, 3, 9)
for ly in range(6, 12):
    for lx in range(22, 30):
        if (lx - 26)**2 / 16.0 + (ly - 8)**2 / 6.0 <= 1.0:
            s_lemon.set(lx, ly, 10)
s_lemon.fill_rect(24, 7, 3, 1, 11)

s_lemon.add_outline_and_glow(range(3, 12))
symbols.append(s_lemon)

# SYMBOL 9: STAR
pal_star = [
    0x0000, # 0: Trans
    0xFFF6, # 1: Cream Halo
    0x1840, # 2: Black Stroke
    0x7A00, # 3: Deep Bronze Shadow (120, 65, 0)
    0xAA60, # 4: Dark Gold (170, 125, 0)
    0xCD00, # 5: Rich Gold (205, 160, 0)
    0xEE40, # 6: Golden Body (235, 195, 0)
    0xFEE0, # 7: Bright Yellow Gold (255, 235, 0)
    0xFF74, # 8: Radiant Light Gold (255, 245, 160)
    0xFFFF, # 9: Brilliant White Center Burst
    0x0000, 0x0000, 0x0000, 0x0000, 0x0000, 0x0000
]
s_star = SymbolBuilder("star", pal_star)
# 5-pointed star: center (18, 19), outer radius 14.5, inner radius 6.0
cx, cy = 18.0, 19.0
outer_r = 14.0
inner_r = 6.0
# 10 vertices
verts = []
for i in range(10):
    ang = -math.pi / 2.0 + i * (math.pi / 5.0)
    r = outer_r if (i % 2 == 0) else inner_r
    verts.append((cx + r * math.cos(ang), cy + r * math.sin(ang)))

# Rasterize star polygon
def point_in_poly(px, py, poly):
    inside = False
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        if ((y1 > py) != (y2 > py)) and (px < (x2 - x1) * (py - y1) / (y2 - y1 + 1e-9) + x1):
            inside = not inside
    return inside

for y in range(4, 34):
    for x in range(4, 34):
        if point_in_poly(x + 0.5, y + 0.5, verts):
            # Facet shading based on angle
            ang = math.atan2(y - cy, x - cx)
            dist = math.hypot(x - cx, y - cy)
            if dist < 3.5:
                s_star.set(x, y, 9) # White center
            elif -math.pi/2 <= ang < -math.pi/6 or math.pi/6 <= ang < math.pi/2:
                s_star.set(x, y, 7 if dist < 8 else 6)
            elif -math.pi/6 <= ang < math.pi/6:
                s_star.set(x, y, 8)
            else:
                s_star.set(x, y, 5 if dist < 8 else 4)

s_star.add_outline_and_glow(range(3, 10))
symbols.append(s_star)

print(f"Designed {len(symbols)} symbols")

# 3. Export to slot_assets.h
header_lines = []
header_lines.append("// =============================================================================")
header_lines.append("//  SLOT MACHINE ASSETS FOR ARDUINO NANO (ST7735 160x128)")
header_lines.append("//  10 High-Fidelity Slot Symbols (36x36, 4-bit nibble indexed, PROGMEM)")
header_lines.append("//  Exact 3D Golden Metallic Cylinder Gradient matching user sample image")
header_lines.append("// =============================================================================")
header_lines.append("")
header_lines.append("#ifndef SLOT_ASSETS_H")
header_lines.append("#define SLOT_ASSETS_H")
header_lines.append("")
header_lines.append("#include <avr/pgmspace.h>")
header_lines.append("#include <stdint.h>")
header_lines.append("")
header_lines.append("// Precalculated 120-line golden metallic cylinder gradient (RGB565)")
header_lines.append("const uint16_t reelGradient[120] PROGMEM = {")
for i in range(0, 120, 8):
    chunk = reel_gradient_565[i:i+8]
    hex_str = ", ".join(f"0x{c:04X}" for c in chunk)
    header_lines.append(f"  {hex_str},")
header_lines.append("};")
header_lines.append("")

header_lines.append("// Palettes for each of the 10 symbols (16 colors each, RGB565)")
header_lines.append("const uint16_t symbolPalettes[10][16] PROGMEM = {")
for sym in symbols:
    header_lines.append(f"  // Symbol: {sym.name.upper()}")
    pal16 = (sym.pal[:16] + [0] * 16)[:16]
    hex_str = ", ".join(f"0x{c:04X}" for c in pal16)
    header_lines.append(f"  {{ {hex_str} }},")
header_lines.append("};")
header_lines.append("")

header_lines.append("// 36x36 Pixel data for 10 symbols (648 bytes per symbol, 4-bit indexed)")
for sym in symbols:
    header_lines.append(f"const uint8_t symbol_{sym.name}[648] PROGMEM = {{")
    bytes_arr = []
    for y in range(SYM_H):
        for x in range(0, SYM_W, 2):
            n0 = sym.grid[y][x] & 0x0F
            n1 = sym.grid[y][x + 1] & 0x0F
            bytes_arr.append((n0 << 4) | n1)
    for i in range(0, 648, 18):
        chunk = bytes_arr[i:i+18]
        hex_str = ", ".join(f"0x{b:02X}" for b in chunk)
        header_lines.append(f"  {hex_str},")
    header_lines.append("};")
    header_lines.append("")

header_lines.append("// Array of pointers to 10 symbols")
header_lines.append("const uint8_t* const symbolBitmaps[10] PROGMEM = {")
for sym in symbols:
    header_lines.append(f"  symbol_{sym.name},")
header_lines.append("};")
header_lines.append("")
header_lines.append("#endif // SLOT_ASSETS_H")

with open("slot_assets.h", "w") as f:
    f.write("\n".join(header_lines) + "\n")

print("Saved slot_assets.h successfully!")

# 4. Generate preview image of all 10 symbols grid
grid_w = 5 * 40
grid_h = 2 * 40
grid = [[(35, 35, 35) for _ in range(grid_w)] for _ in range(grid_h)]
for i, sym in enumerate(symbols):
    col = i % 5
    row = i // 5
    ox = col * 40 + 2
    oy = row * 40 + 2
    for y in range(SYM_H):
        for x in range(SYM_W):
            n = sym.grid[y][x]
            if n != 0:
                grid[oy + y][ox + x] = rgb565_to_rgb888(sym.pal[n])

save_bmp("preview_all_symbols.bmp", grid_w, grid_h, grid)
print("Saved preview_all_symbols.bmp")

# 5. Generate full 160x128 slot machine mockup
frame = [[(10, 12, 11) for _ in range(160)] for _ in range(128)]
reel_x_pos = [6, 57, 108]
REEL_WIDTH = 46
REEL_INNER_W = 42
REEL_HEIGHT = 120
SLOT_H = 46

# Colors for frame & borders
C_GOLD_DARK = rgb565_to_rgb888(0x9C42)
C_GOLD_BRIGHT = rgb565_to_rgb888(0xFFE0)
C_RED = rgb565_to_rgb888(0xF800)
C_CREAM = (255, 255, 230)

# Strips: reel 0: 0, reel 1: 0, reel 2: 0 (Jackpot Dollar Dollar Dollar)
# Top: sym 9 (star), Mid: sym 0 (dollar), Bot: sym 1 (bar)
for r_idx in range(3):
    rx = reel_x_pos[r_idx]
    # Draw cylinder background
    for y in range(REEL_HEIGHT):
        bg = rgb565_to_rgb888(reel_gradient_565[y])
        for x in range(REEL_INNER_W):
            frame[4 + y][rx + 2 + x] = bg
    
    # Draw middle symbol (Dollar, sym 0) centered at y=64 (screen y = 46..81)
    sym0 = symbols[0]
    for sy in range(SYM_H):
        py = 46 + sy
        for sx in range(SYM_W):
            px = rx + 2 + 3 + sx
            n = sym0.grid[sy][sx]
            if n != 0:
                frame[py][px] = rgb565_to_rgb888(sym0.pal[n])
                
    # Draw top symbol (partially visible, bottom rows)
    # y ranges from 0 to 45 (slot center is y=0, symbol spans screen y=0..35 - 18 = 0..17)
    top_sym = symbols[3 if r_idx==1 else (2 if r_idx==2 else 4)] # melon, cherry, plum
    for sy in range(SYM_H):
        py = 46 - SLOT_H + sy
        if 4 <= py < 4 + REEL_HEIGHT:
            for sx in range(SYM_W):
                px = rx + 2 + 3 + sx
                n = top_sym.grid[sy][sx]
                if n != 0:
                    frame[py][px] = rgb565_to_rgb888(top_sym.pal[n])

    # Draw bottom symbol (partially visible, top rows)
    bot_sym = symbols[1 if r_idx==1 else (2 if r_idx==2 else 1)] # bar, cherry, bar
    for sy in range(SYM_H):
        py = 46 + SLOT_H + sy
        if 4 <= py < 4 + REEL_HEIGHT:
            for sx in range(SYM_W):
                px = rx + 2 + 3 + sx
                n = bot_sym.grid[sy][sx]
                if n != 0:
                    frame[py][px] = rgb565_to_rgb888(bot_sym.pal[n])

    # Draw rounded border
    # Outer
    for x in range(rx, rx + REEL_WIDTH):
        frame[3][x] = C_GOLD_DARK
        frame[3 + REEL_HEIGHT + 1][x] = C_GOLD_DARK
    for y in range(3, 3 + REEL_HEIGHT + 2):
        frame[y][rx] = C_GOLD_DARK
        frame[y][rx + REEL_WIDTH - 1] = C_GOLD_DARK
    # Inner gold
    for x in range(rx + 1, rx + REEL_WIDTH - 1):
        frame[4][x] = C_CREAM
        frame[4 + REEL_HEIGHT - 1][x] = C_CREAM
    for y in range(4, 4 + REEL_HEIGHT):
        frame[y][rx + 1] = C_CREAM
        frame[y][rx + REEL_WIDTH - 2] = C_CREAM

# Payline indicators on left and right
for dy in range(-4, 5):
    y = 64 + dy
    length = 5 - abs(dy)
    for x in range(length + 1):
        frame[y][x] = C_GOLD_BRIGHT if (x == length or abs(dy) >= 3) else C_RED
    for x in range(159 - length, 160):
        frame[y][x] = C_GOLD_BRIGHT if (x == 159 - length or abs(dy) >= 3) else C_RED

save_bmp("mockup_fullscreen.bmp", 160, 128, frame)
print("Saved mockup_fullscreen.bmp")
