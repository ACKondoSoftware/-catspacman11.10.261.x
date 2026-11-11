#!/usr/bin/env python3
# cat's maze chase 0.1 -- single-file maze-chase arcade
# pip install pygame-ce   |   python cats_maze_chase_0_1.py
# Windows 10+ / macOS. 60 FPS fixed step. Engine: import math.
import array
import math
import random
import io
import wave
import sys

import pygame

TITLE = "Cat's Pac-Man 0.1.1"
FPS = 60
T = 24                                   # tile size in px
HUD_TOP, HUD_BOT = 40, 32

# Left half of the maze (cols 0..10); mirrored to 21 columns.
# '#' wall  '.' kibble  'o' catnip  '-' pen door  ' ' open floor
HALF = [
    "###########",
    "#.........#",
    "#o##.####.#",
    "#..........",
    "#.##.#.####",
    "#....#....#",
    "####.####.#",
    "#....#     ",
    "####.#  ##-",
    "    .   #  ",
    "####.#  ###",
    "#....#     ",
    "#.##.####.#",
    "#..........",
    "#.##.#.####",
    "#o...#....#",
    "####.####.#",
    "#..........",
    "#.#######.#",
    "#.........#",
    "###########",
]
MAZE = [r + r[9::-1] for r in HALF]
COLS, ROWS = len(MAZE[0]), len(MAZE)
W, H = COLS * T, HUD_TOP + ROWS * T + HUD_BOT

HOME = (10, 7)                           # tile above the pen door
PEN = (10, 9)
START = (10, 11)
TUNNEL_ROW = 9
DIRS = [(0, -1), (-1, 0), (0, 1), (1, 0)]  # tie-break order: up, left, down, right

# Arcade timing: full speed = 75.7576 px/s on an 8 px grid -> tiles per frame.
BASE = 75.7576 / 8.0 / FPS


def speeds(level):
    """(cat, cat_on_catnip, bot, bot_scared, bot_tunnel) as fractions of BASE."""
    if level == 1:
        return 0.80, 0.90, 0.75, 0.50, 0.40
    if level <= 4:
        return 0.90, 0.95, 0.85, 0.55, 0.45
    return 1.00, 1.00, 0.95, 0.60, 0.50


MODE_PLAN = [7, 20, 7, 20, 5, 20, 5]     # scatter/chase seconds, then chase forever

BLACK = (6, 8, 16)
WALL_FILL = (16, 34, 52)
WALL_EDGE = (64, 208, 196)
DOOR = (255, 190, 90)
KIBBLE = (250, 232, 200)
CATNIP = (110, 230, 110)
ORANGE = (255, 160, 60)
PINK = (255, 150, 170)
WHITE = (240, 240, 240)
GREY = (140, 150, 165)
BOT_COLS = [(240, 80, 80), (250, 150, 220), (90, 220, 240), (250, 180, 70)]
CORNERS = [(COLS - 2, 0), (1, 0), (COLS - 2, ROWS - 1), (1, ROWS - 1)]


def is_open(x, y):
    if y < 0 or y >= ROWS:
        return False
    return MAZE[y][x % COLS] not in "#-"


class Mover:
    """Grid mover: tile (tx,ty), direction d, progress p in [0,1) toward next tile."""

    def __init__(self, tx, ty, d=(0, 0)):
        self.tx, self.ty, self.d, self.p = tx, ty, d, 0.0

    @property
    def fx(self):
        return self.tx + self.d[0] * self.p

    @property
    def fy(self):
        return self.ty + self.d[1] * self.p

    def reverse(self):
        if self.d != (0, 0):
            self.tx = (self.tx + self.d[0]) % COLS
            self.ty += self.d[1]
            self.d = (-self.d[0], -self.d[1])
            self.p = 1.0 - self.p

    def step(self, speed, choose, arrive=None):
        if self.d == (0, 0):
            self.d = choose(self)
            if self.d == (0, 0):
                return
        self.p += speed
        while self.p >= 1.0:
            self.p -= 1.0
            self.tx = (self.tx + self.d[0]) % COLS
            self.ty += self.d[1]
            if arrive:
                arrive(self)
            self.d = choose(self)
            if self.d == (0, 0):
                self.p = 0.0
                break


class Bot(Mover):
    def __init__(self, idx):
        super().__init__(*PEN)
        self.idx = idx
        self.mode = "pen"                # pen | out | eyes
        self.timer = 0
        self.scared = False


class Audio:
    """Original synthesized arcade soundtrack; no external audio files."""
    SR = 22050

    def __init__(self):
        self.ok = False
        self.enabled = True
        self.snd = {}
        self.music_kind = None
        self.music_channel = None
        self.last_waka = 0
        self.waka_flip = False
        try:
            if not pygame.mixer.get_init():
                pygame.mixer.init(frequency=self.SR, size=-16, channels=1, buffer=512)
            pygame.mixer.set_num_channels(12)
            self.music_channel = pygame.mixer.Channel(0)
            self.snd = {
                'waka1': self.effect(360, 520, 70, .14),
                'waka2': self.effect(480, 310, 70, .14),
                'nip': self.effect(180, 880, 360, .24),
                'bot': self.effect(280, 1200, 280, .25),
                'die': self.effect(900, 90, 950, .23),
                'sel': self.effect(720, 900, 85, .13),
                'win': self.effect(420, 1280, 700, .21),
                'rollcall': self.song([(0, 523, 110), (150, 659, 110),
                                       (300, 784, 110), (450, 1047, 230),
                                       (750, 784, 100), (900, 1047, 300)], 1400),
                'intro': self.song([(0, 392, 130), (150, 523, 130), (300, 659, 130),
                                    (450, 784, 240), (760, 659, 130),
                                    (910, 784, 130), (1060, 1047, 340)], 1600),
                'menu': self.song([(0, 392, 140), (250, 494, 140), (500, 587, 140),
                                   (750, 784, 140), (1000, 587, 140),
                                   (1250, 494, 140)], 1500),
                'game': self.song([(0, 196, 110), (180, 294, 110), (360, 392, 110),
                                   (540, 294, 110), (720, 220, 110),
                                   (900, 330, 110), (1080, 440, 110),
                                   (1260, 330, 110)], 1440),
                'fright': self.song([(0, 165, 95), (150, 196, 95),
                                     (300, 175, 95), (450, 147, 95)], 600),
            }
            self.ok = True
        except (pygame.error, ValueError, OSError):
            self.ok = False

    def effect(self, f0, f1, ms, vol):
        count = int(self.SR * ms / 1000)
        data = array.array('h')
        phase = 0.0
        for i in range(count):
            phase += 2 * math.pi * (f0 + (f1 - f0) * i / max(1, count)) / self.SR
            envelope = min(1., i / max(1, count * .03),
                           (count - i) / max(1, count * .25))
            data.append(int(32767 * vol * envelope * (1 if math.sin(phase) > 0 else -1)))
        return pygame.mixer.Sound(buffer=data.tobytes())

    def song(self, notes, duration_ms):
        """Compose a looping original 8-bit pattern into an in-memory buffer."""
        count = int(self.SR * duration_ms / 1000)
        data = array.array('h', [0]) * count
        for start_ms, freq, length_ms in notes:
            start = int(self.SR * start_ms / 1000)
            length = int(self.SR * length_ms / 1000)
            for j in range(min(length, count - start)):
                phase = j * freq / self.SR
                square = 1 if phase % 1 < .5 else -1
                env = min(1., j / max(1, length * .04),
                          (length - j) / max(1, length * .18))
                idx = start + j
                data[idx] = max(-32768, min(32767, data[idx] + int(3500 * square * env)))
        return pygame.mixer.Sound(buffer=data.tobytes())

    def play(self, name):
        if not self.ok or not self.enabled:
            return
        if name == 'eat':
            # Alternate the two chomps; throttle to avoid sound overlap.
            now = pygame.time.get_ticks()
            if now - self.last_waka < 65:
                return
            self.last_waka = now
            self.waka_flip = not self.waka_flip
            name = 'waka1' if self.waka_flip else 'waka2'
        sound = self.snd.get(name)
        if sound:
            pygame.mixer.find_channel(True).play(sound)

    def sync_music(self, active, frightened=False, menu=False):
        if not self.ok:
            return
        kind = ('menu' if menu else 'fright' if frightened else 'game') if active and self.enabled else None
        if kind != self.music_kind:
            self.music_channel.stop()
            self.music_kind = kind
            if kind:
                self.music_channel.play(self.snd[kind], loops=-1)

    def toggle(self):
        self.enabled = not self.enabled
        if not self.enabled and self.ok:
            pygame.mixer.stop()
            self.music_kind = None
        return self.enabled


def draw_cat(surf, cx, cy, r, d=(1, 0), t=0, moving=False):
    """Classic circular yellow chomper, animated in the direction of travel."""
    cx, cy, r = int(cx), int(cy), max(2, int(r))
    direction = d if d != (0, 0) else (1, 0)
    heading = math.atan2(-direction[1], direction[0])
    mouth = (0.08 + 0.52 * abs(math.sin(t * 0.21))) if moving else 0.12
    points = [(cx, cy)]
    for i in range(37):
        angle = heading + mouth + (2 * math.pi - 2 * mouth) * i / 36
        points.append((int(cx + r * math.cos(angle)), int(cy - r * math.sin(angle))))
    pygame.draw.polygon(surf, (255, 220, 0), points)


def draw_bot(surf, cx, cy, r, col, d=(0, 0), t=0):
    """Colorful ghost with rounded head, wavy skirt and directional eyes."""
    cx, cy, r = int(cx), int(cy), max(3, int(r))
    pygame.draw.circle(surf, col, (cx, cy - r // 5), r)
    pygame.draw.rect(surf, col, (cx-r, cy-r//5, 2*r, r+ r//4))
    bottom = cy + r
    points = [(cx-r, cy), (cx+r, cy), (cx+r, bottom)]
    for j in range(6, -1, -1):
        x = cx-r + (2*r*j/6)
        y = bottom - (r//4 if j % 2 else 0)
        points.append((int(x), int(y)))
    pygame.draw.polygon(surf, col, points)
    for offset in (-r//3, r//3):
        ex, ey = cx+offset, cy-r//4
        pygame.draw.ellipse(surf, WHITE, (ex-r*.22, ey-r*.35, r*.44, r*.70))
        pygame.draw.circle(surf, (28, 55, 200),
                           (int(ex+d[0]*r*.10), int(ey+d[1]*r*.13)), max(1, r//7))


class Game:
    MENU = ["PLAY GAME", "HELP", "ABOUT", "COPYRIGHT", "EXIT"]
    PAGES = {
        "HELP": [
            "HOW TO PLAY", "",
            "Arrow keys / WASD   steer the cat",
            "P                   pause",
            "M                   mute / unmute",
            "R                   restart run",
            "ESC                 back to menu", "",
            "Eat every dot to clear the maze.",
            "Ghosts end a life on contact.",
            "Power pellets scare ghosts: eat them",
            "for 200 / 400 / 800 / 1600.",
            "Side tunnel wraps around; bots crawl in it.",
            "Extra cat at 10,000 points.",
        ],
        "ABOUT": [
            "ABOUT", "",
            TITLE,
            "Single-file maze chase in pygame-ce.",
            "Fixed 60 FPS step, arcade speed table:",
            "full speed = 75.76 px/s on an 8 px grid.",
            "Movement, ghost AI and chiptune synth",
            "are generated with Python math.", "",
            "Runs on Windows 10+ and macOS.",
        ],
        "COPYRIGHT": [
            "COPYRIGHT", "",
            "(C) 2026 A.C Holdings / Team Flames",
            "",
            "Original code and synthesized soundtrack.",
            "No third-party assets.",
        ],
    }

    def __init__(self, screen):
        self.screen = screen
        self.fonts = {}
        self.audio = Audio()
        self.t = 0
        self.state = "menu"              # menu | page | play
        self.page = None
        self.sel = 0
        self.high = 0
        self.running = True
        self.maze_surf = self.build_maze()
        self.new_run()

    # ---------- setup ----------
    def font(self, size):
        if size not in self.fonts:
            self.fonts[size] = pygame.font.Font(None, size)
        return self.fonts[size]

    def text(self, s, size, col, x, y, center=True):
        img = self.font(size).render(s, True, col)
        r = img.get_rect()
        if center:
            r.center = (x, y)
        else:
            r.topleft = (x, y)
        self.screen.blit(img, r)
        return r

    def build_maze(self):
        s = pygame.Surface((COLS * T, ROWS * T))
        s.fill(BLACK)
        for y, row in enumerate(MAZE):
            for x, c in enumerate(row):
                px, py = x * T, y * T
                if c == "#":
                    pygame.draw.rect(s, WALL_FILL, (px, py, T, T))
                    for dx, dy, a, b in ((0, -1, (px, py), (px + T - 1, py)),
                                         (0, 1, (px, py + T - 1), (px + T - 1, py + T - 1)),
                                         (-1, 0, (px, py), (px, py + T - 1)),
                                         (1, 0, (px + T - 1, py), (px + T - 1, py + T - 1))):
                        nx, ny = x + dx, y + dy
                        if 0 <= nx < COLS and 0 <= ny < ROWS and MAZE[ny][nx] != "#":
                            pygame.draw.line(s, WALL_EDGE, a, b, 2)
                elif c == "-":
                    pygame.draw.rect(s, DOOR, (px, py + T // 2 - 2, T, 4))
        return s

    def new_run(self):
        self.score = 0
        self.lives = 3
        self.level = 1
        self.bonus_life = False
        self.paused = False
        self.new_level()

    def new_level(self):
        self.kibble, self.catnip = set(), set()
        for y, row in enumerate(MAZE):
            for x, c in enumerate(row):
                if c == ".":
                    self.kibble.add((x, y))
                elif c == "o":
                    self.catnip.add((x, y))
        self.total = len(self.kibble) + len(self.catnip)
        self.fish = 0                    # bonus fish frames remaining
        self.fish_done = False
        self.reset_actors()

    def reset_actors(self):
        self.cat = Mover(*START)
        self.want = (0, 0)
        self.bots = [Bot(i) for i in range(4)]
        b0 = self.bots[0]
        b0.mode, b0.tx, b0.ty, b0.d = "out", HOME[0], HOME[1], (-1, 0)
        for b, secs in zip(self.bots[1:], (2, 5, 8)):
            b.timer = secs * FPS
        self.fright = 0
        self.combo = 0
        self.plan_i = 0
        self.plan_t = MODE_PLAN[0] * FPS
        self.phase = "ready"             # ready | run | eat | dying | clear | over
        self.phase_t = 2 * FPS
        self.popup = None

    # ---------- input ----------
    def handle(self, ev):
        if ev.type == pygame.QUIT:
            self.running = False
        elif ev.type == pygame.KEYDOWN:
            self.key(ev.key)
        elif ev.type == pygame.MOUSEMOTION and self.state == "menu":
            i = self.menu_hit(ev.pos)
            if i is not None:
                self.sel = i
        elif ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
            if self.state == "menu":
                i = self.menu_hit(ev.pos)
                if i is not None:
                    self.sel = i
                    self.pick()
            elif self.state == "page":
                self.state = "menu"

    def menu_hit(self, pos):
        for i in range(len(self.MENU)):
            if pygame.Rect(W // 2 - 110, 268 + i * 44, 220, 38).collidepoint(pos):
                return i
        return None

    def pick(self):
        self.audio.play("sel")
        item = self.MENU[self.sel]
        if item == "PLAY GAME":
            self.new_run()
            self.state = "play"
            self.audio.play("rollcall")
            self.audio.play("intro")
        elif item == "EXIT":
            self.running = False
        else:
            self.page, self.state = item, "page"

    def key(self, k):
        if self.state == "menu":
            if k == pygame.K_m:
                self.audio.toggle()
            elif k in (pygame.K_UP, pygame.K_w):
                self.sel = (self.sel - 1) % len(self.MENU)
            elif k in (pygame.K_DOWN, pygame.K_s):
                self.sel = (self.sel + 1) % len(self.MENU)
            elif k in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE):
                self.pick()
            elif k == pygame.K_ESCAPE:
                self.running = False
        elif self.state == "page":
            if k in (pygame.K_ESCAPE, pygame.K_RETURN, pygame.K_KP_ENTER,
                     pygame.K_SPACE, pygame.K_BACKSPACE):
                self.state = "menu"
        else:
            if k == pygame.K_ESCAPE:
                self.state = "menu"
            elif k == pygame.K_m:
                self.audio.toggle()
            elif k == pygame.K_p:
                self.paused = not self.paused
            elif k == pygame.K_r:
                self.new_run()
            elif k in (pygame.K_UP, pygame.K_w):
                self.want = (0, -1)
            elif k in (pygame.K_DOWN, pygame.K_s):
                self.want = (0, 1)
            elif k in (pygame.K_LEFT, pygame.K_a):
                self.want = (-1, 0)
            elif k in (pygame.K_RIGHT, pygame.K_d):
                self.want = (1, 0)

    # ---------- simulation ----------
    def add_score(self, n):
        self.score += n
        self.high = max(self.high, self.score)
        if not self.bonus_life and self.score >= 10000:
            self.bonus_life = True
            self.lives += 1
            self.audio.play("win")

    def choose_cat(self, m):
        w = self.want
        if w != (0, 0) and is_open(m.tx + w[0], m.ty + w[1]):
            return w
        if m.d != (0, 0) and is_open(m.tx + m.d[0], m.ty + m.d[1]):
            return m.d
        return (0, 0)

    def cat_arrive(self, m):
        pos = (m.tx, m.ty)
        if pos in self.kibble:
            self.kibble.discard(pos)
            self.add_score(10)
            self.audio.play("eat")
        elif pos in self.catnip:
            self.catnip.discard(pos)
            self.add_score(50)
            self.audio.play("nip")
            self.fright = max(1, 7 - self.level) * FPS
            self.combo = 0
            for b in self.bots:
                if b.mode == "out":
                    b.scared = True
                    b.reverse()
        elif self.fish and pos == START:
            self.fish = 0
            pts = 100 * min(self.level, 8)
            self.add_score(pts)
            self.audio.play("bot")
        eaten = self.total - len(self.kibble) - len(self.catnip)
        if not self.fish_done and eaten >= self.total // 2:
            self.fish_done = True
            self.fish = 9 * FPS

    def target(self, b):
        if b.mode == "eyes":
            return HOME
        if self.plan_i % 2 == 0 and self.plan_i < len(MODE_PLAN):
            return CORNERS[b.idx]        # scatter
        c = self.cat
        cd = c.d if c.d != (0, 0) else self.want
        if b.idx == 0:                   # chaser
            return c.tx, c.ty
        if b.idx == 1:                   # ambusher: four tiles ahead
            return c.tx + 4 * cd[0], c.ty + 4 * cd[1]
        if b.idx == 2:                   # flanker: mirror the chaser through the cat
            ax, ay = c.tx + 2 * cd[0], c.ty + 2 * cd[1]
            return 2 * ax - self.bots[0].tx, 2 * ay - self.bots[0].ty
        if math.hypot(b.tx - c.tx, b.ty - c.ty) > 6:   # wanderer
            return c.tx, c.ty
        return CORNERS[3]

    def choose_bot(self, b):
        rev = (-b.d[0], -b.d[1])
        opts = [d for d in DIRS if d != rev and is_open(b.tx + d[0], b.ty + d[1])]
        if not opts:
            return rev if is_open(b.tx + rev[0], b.ty + rev[1]) else (0, 0)
        if b.scared:
            return random.choice(opts)
        tx, ty = self.target(b)
        return min(opts, key=lambda d: math.hypot(b.tx + d[0] - tx, b.ty + d[1] - ty))

    def update(self):
        self.t += 1
        if self.state != "play" or self.paused:
            return
        if self.phase != "run":
            self.phase_t -= 1
            if self.phase_t <= 0:
                if self.phase in ("ready", "eat"):
                    self.phase, self.popup = "run", None
                elif self.phase == "dying":
                    self.lives -= 1
                    if self.lives <= 0:
                        self.phase, self.phase_t = "over", 3 * FPS
                    else:
                        self.reset_actors()
                elif self.phase == "clear":
                    self.level += 1
                    self.new_level()
                elif self.phase == "over":
                    self.state = "menu"
            return

        sc, sc_nip, sb, sb_scared, sb_tun = speeds(self.level)

        # cat
        c = self.cat
        if c.d != (0, 0) and self.want == (-c.d[0], -c.d[1]):
            c.reverse()
        c.step(BASE * (sc_nip if self.fright else sc), self.choose_cat, self.cat_arrive)

        # timers
        if self.fish:
            self.fish -= 1
        if self.fright:
            self.fright -= 1
            if self.fright == 0:
                for b in self.bots:
                    b.scared = False
        elif self.plan_i < len(MODE_PLAN):
            self.plan_t -= 1
            if self.plan_t <= 0:
                self.plan_i += 1
                if self.plan_i < len(MODE_PLAN):
                    self.plan_t = MODE_PLAN[self.plan_i] * FPS
                for b in self.bots:
                    if b.mode == "out":
                        b.reverse()

        # bots
        for b in self.bots:
            if b.mode == "pen":
                b.timer -= 1
                if b.timer <= 0:
                    b.mode, b.tx, b.ty, b.p = "out", HOME[0], HOME[1], 0.0
                    b.d = random.choice([(-1, 0), (1, 0)])
                continue
            if b.mode == "eyes":
                sp = 2.0
            elif b.scared:
                sp = sb_scared
            elif b.ty == TUNNEL_ROW and (b.tx < 4 or b.tx > COLS - 5):
                sp = sb_tun
            else:
                sp = sb
            b.step(BASE * sp, self.choose_bot)
            if b.mode == "eyes" and (b.tx, b.ty) == HOME:
                b.mode, b.tx, b.ty, b.d, b.p = "pen", PEN[0], PEN[1], (0, 0), 0.0
                b.timer = 2 * FPS

        # contact
        for b in self.bots:
            if b.mode != "out":
                continue
            if math.hypot(b.fx - c.fx, b.fy - c.fy) < 0.6:
                if b.scared:
                    pts = 200 * (2 ** self.combo)
                    self.combo = min(self.combo + 1, 3)
                    self.add_score(pts)
                    b.mode, b.scared = "eyes", False
                    self.popup = (str(pts), c.fx, c.fy)
                    self.phase, self.phase_t = "eat", FPS // 2
                    self.audio.play("bot")
                else:
                    self.phase, self.phase_t = "dying", int(1.5 * FPS)
                    self.audio.play("die")
                return

        if not self.kibble and not self.catnip:
            self.phase, self.phase_t = "clear", 2 * FPS
            self.audio.play("win")

    # ---------- rendering ----------
    def px(self, fx, fy):
        return fx * T + T // 2, HUD_TOP + fy * T + T // 2

    def draw(self):
        self.screen.fill(BLACK)
        if self.state == "menu":
            self.draw_menu()
        elif self.state == "page":
            self.draw_page()
        else:
            self.draw_play()

    def draw_menu(self):
        t = self.t
        self.text("CAT'S", 54, (255, 220, 0), W // 2, 70)
        self.text("PAC-MAN", 72, WALL_EDGE, W // 2, 122)
        self.text("0.1.1  -  ORIGINAL CHIPTUNE", 25, GREY, W // 2, 164)
        x = (t * 2) % (W + 240) - 120
        draw_cat(self.screen, x, 218, 16, (1, 0), t, True)
        for i, col in enumerate(BOT_COLS):
            draw_bot(self.screen, x - 60 - i * 34, 220 + math.sin(t * 0.15 + i) * 2,
                     12, col, (1, 0), t)
        for i, item in enumerate(self.MENU):
            on = i == self.sel
            r = pygame.Rect(W // 2 - 110, 268 + i * 44, 220, 38)
            pygame.draw.rect(self.screen, WALL_FILL if on else BLACK, r, border_radius=8)
            pygame.draw.rect(self.screen, WALL_EDGE if on else (40, 60, 80), r, 2,
                             border_radius=8)
            self.text(item, 30, WHITE if on else GREY, r.centerx, r.centery)
        self.text("HIGH SCORE  %d" % self.high, 24, KIBBLE, W // 2, H - 56)
        self.text("(C) AC Kondo 1999-2026", 20, GREY, W // 2, H - 26)

    def draw_page(self):
        lines = self.PAGES[self.page]
        self.text(lines[0], 48, WALL_EDGE, W // 2, 90)
        y = 160
        for ln in lines[1:]:
            if ln:
                self.text(ln, 24, WHITE, W // 2, y)
            y += 28
        if (self.t // 30) % 2:
            self.text("ESC / ENTER  -  back", 22, GREY, W // 2, H - 40)

    def draw_play(self):
        t, scr = self.t, self.screen
        flash = self.phase == "clear" and (self.phase_t // 12) % 2
        scr.blit(self.maze_surf, (0, HUD_TOP))
        if flash:
            veil = pygame.Surface((COLS * T, ROWS * T))
            veil.fill((60, 60, 60))
            scr.blit(veil, (0, HUD_TOP), special_flags=pygame.BLEND_RGB_ADD)

        for (x, y) in self.kibble:
            pygame.draw.circle(scr, KIBBLE, self.px(x, y), 3)
        pulse = 6 + math.sin(t * 0.2) * 2
        for (x, y) in self.catnip:
            cx, cy = self.px(x, y)
            pygame.draw.ellipse(scr, CATNIP, (cx - pulse, cy - pulse * 0.6,
                                              pulse * 2, pulse * 1.2))
            pygame.draw.line(scr, (40, 120, 40), (cx - pulse, cy), (cx + pulse, cy), 1)
        if self.fish and (self.fish > 2 * FPS or (t // 8) % 2):
            cx, cy = self.px(*START)
            pygame.draw.ellipse(scr, (120, 200, 255), (cx - 8, cy - 4, 13, 9))
            pygame.draw.polygon(scr, (120, 200, 255),
                                [(cx + 3, cy), (cx + 10, cy - 5), (cx + 10, cy + 5)])
            pygame.draw.circle(scr, BLACK, (cx - 4, cy - 1), 1)

        if self.phase not in ("dying", "over"):
            for b in self.bots:
                cx, cy = self.px(b.fx, b.fy)
                if b.mode == "eyes":
                    pygame.draw.circle(scr, BOT_COLS[b.idx], (cx, cy), 4, 2)
                    continue
                col = BOT_COLS[b.idx]
                if b.scared:
                    col = (80, 120, 255)
                    if self.fright < 2 * FPS and (self.fright // 10) % 2:
                        col = WHITE
                bob = math.sin(t * 0.25 + b.idx) * 1.5 if b.mode == "pen" else 0
                ox = (b.idx - 2) * 20 if b.mode == "pen" else 0
                draw_bot(scr, cx + ox, cy + bob, 10, col, b.d, t)

        c = self.cat
        cx, cy = self.px(c.fx, c.fy)
        if self.phase == "dying":
            k = max(0.0, self.phase_t / (1.5 * FPS))
            draw_cat(scr, cx + math.sin(t * 0.9) * 3 * k, cy, max(2, int(11 * k)),
                     (0, 0), 1)
        elif self.phase != "over" and not self.popup:
            face = c.d if c.d != (0, 0) else (0, 0)
            draw_cat(scr, cx, cy, 11, face, t, c.d != (0, 0))
        if self.popup:
            s, fx, fy = self.popup
            self.text(s, 22, (120, 240, 255), *self.px(fx, fy))

        # wrap masks so sprites slide out of view in the tunnel cleanly
        self.text("SCORE  %d" % self.score, 26, WHITE, 10, 10, False)
        self.text("HIGH  %d" % self.high, 26, KIBBLE, W // 2, 20)
        r = self.font(26).render("LEVEL  %d" % self.level, True, WHITE)
        scr.blit(r, (W - r.get_width() - 10, 10))
        by = HUD_TOP + ROWS * T + HUD_BOT // 2
        for i in range(max(0, self.lives - 1)):
            draw_cat(scr, 18 + i * 26, by + 2, 8, (0, 0), 1)
        r = self.font(18).render("P pause   M mute   R restart   ESC menu", True, GREY)
        scr.blit(r, (W - r.get_width() - 10, by - r.get_height() // 2))

        mid = self.px(HOME[0], 11)
        if self.phase == "ready":
            self.text("READY!", 30, KIBBLE, mid[0], mid[1] + T)
        elif self.phase == "over":
            self.text("GAME OVER", 34, (240, 80, 80), *mid)
        elif self.phase == "clear":
            self.text("MAZE CLEAR", 30, CATNIP, mid[0], mid[1] + T)
        if self.paused:
            veil = pygame.Surface((W, H), pygame.SRCALPHA)
            veil.fill((0, 0, 0, 150))
            scr.blit(veil, (0, 0))
            self.text("PAUSED", 56, WHITE, W // 2, H // 2 - 10)
            self.text("P to resume", 24, GREY, W // 2, H // 2 + 30)


def main():
    pygame.init()
    try:
        screen = pygame.display.set_mode((W, H), pygame.SCALED | pygame.RESIZABLE)
    except pygame.error:
        screen = pygame.display.set_mode((W, H))
    pygame.display.set_caption(TITLE)
    clock = pygame.time.Clock()
    game = Game(screen)
    while game.running:
        for ev in pygame.event.get():
            game.handle(ev)
        game.update()
        game.audio.sync_music((game.state == "menu" or (game.state == "play" and not game.paused and game.phase == "run")),
                              frightened=(game.state == "play" and game.fright > 0),
                              menu=(game.state == "menu"))
        game.draw()
        pygame.display.flip()
        clock.tick(FPS)
    pygame.quit()
    sys.exit(0)


if __name__ == "__main__":
    main()
