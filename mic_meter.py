# -*- coding: utf-8 -*-
"""
麦克风实时声强显示器 v0.0.14
功能：实时显示麦克风音量（竖排圆角蜂窝格 + 分贝值 + dB 单位）
特点：深色面板+细边框、饱和度更高的彩虹格、更窄更高的柱格、整体更小巧、
      悬停显示右上角 × 关闭、版本号常显
交互：鼠标悬停显示 ×（点击关闭）/ 右键 / ESC 退出；左键拖动窗口
运行：双击 重启显示器.bat （或 dist\\麦克风声强显示器.exe）
"""
import numpy as np
import sounddevice as sd
import tkinter as tk
import math

# ================= 参数 =================
VERSION = "v0.0.14"
SAMPLE_RATE = 44100
BLOCK = 2048
CELLS = 15                  # 格数（15 格，单格更矮）
SMOOTH = 0.6
DB_MIN, DB_MAX = -60.0, -6.0

# 窗口尺寸（更窄、整体更小，柱格更高）
W, H = 60, 430
PANEL_M = 2                 # 面板边距
PANEL_R = 6                 # 面板圆角（更小，刚劲有棱角、少毛边）
CELLS_PAD_X = 8
CELLS_PAD_Y = 12
CELL_GAP = 3
TEXT_ZONE = 96              # 底部文字区高度（更紧凑）

# 颜色渐变：底部少量红 -> 快速过渡绿 -> 黄 -> 顶部深蓝
ANCHORS = [
    (0.00, (255, 55, 55)),      # 红（仅底部少量）
    (0.12, (255, 110, 60)),     # 红->橙（快速过渡）
    (0.30, (0, 230, 118)),      # 绿
    (0.55, (255, 215, 0)),      # 黄
    (0.78, (0, 170, 210)),      # 青（过渡）
    (1.00, (25, 55, 190)),      # 深蓝（最顶）
]

COL_BG = "#0f0f14"          # 透明键色（面板外透明）
COL_PANEL = "#16161f"       # 深色面板背景
COL_BORDER = "#8f8fa2"      # 细边框（浅灰，与深色背景有色差但不过亮）
COL_CELL_OFF = "#23232f"
COL_CLOSE = "#e8e8f0"
COL_CLOSE_HOVER = "#ff4d4d"
COL_TEXT = "#f1f2f6"
COL_TEXT_DIM = "#9a9aa8"
COL_VERSION = "#6f6f7e"


def level_color(ratio):
    for i in range(len(ANCHORS) - 1):
        r0, c0 = ANCHORS[i]
        r1, c1 = ANCHORS[i + 1]
        if r0 <= ratio <= r1:
            t = (ratio - r0) / (r1 - r0)
            rgb = tuple(int(c0[j] + (c1[j] - c0[j]) * t) for j in range(3))
            return "#%02x%02x%02x" % rgb
    return "#ff3737"


def round_rect(cv, x1, y1, x2, y2, r, **kw):
    r = max(0, min(r, (x2 - x1) / 2.0, (y2 - y1) / 2.0))
    pts = []
    for cx, cy, a0 in [(x1 + r, y1 + r, 180.0), (x2 - r, y1 + r, 270.0),
                       (x2 - r, y2 - r, 0.0), (x1 + r, y2 - r, 90.0)]:
        for k in range(6):
            a = math.radians(a0 + k * 90.0 / 5)
            pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return cv.create_polygon(pts, smooth=True, **kw)


class MicMeter:
    def __init__(self, root):
        self.root = root
        root.title("麦克风声强显示器 %s" % VERSION)
        root.geometry("%dx%d" % (W, H))
        root.resizable(False, False)
        root.configure(bg=COL_BG)

        # 启动时窗口居中
        root.update_idletasks()
        _sw = root.winfo_screenwidth()
        _sh = root.winfo_screenheight()
        _px = max(0, (_sw - W) // 2)
        _py = max(0, (_sh - H) // 2)
        root.geometry("%dx%d+%d+%d" % (W, H, _px, _py))

        root.overrideredirect(True)
        root.attributes("-topmost", True)
        # 透明背景：COL_BG 颜色全部变透明（面板外悬浮桌面）
        try:
            root.attributes("-transparentcolor", COL_BG)
        except Exception:
            pass

        self.volume = 0
        self.dbfs = -100.0
        self.clipping = False
        self._drag = None
        self._close_after = None

        # ---------- 画布（覆盖整个窗口） ----------
        self.cv = tk.Canvas(root, width=W, height=H, bg=COL_BG,
                            highlightthickness=0)
        self.cv.pack()

        # 深色面板 + 细边框（质感）
        round_rect(self.cv, PANEL_M, PANEL_M, W - PANEL_M, H - PANEL_M,
                   PANEL_R, fill=COL_PANEL, outline=COL_BORDER, width=1)

        # ---------- 蜂窝格（更窄、更高） ----------
        self.cell_rects = []
        cw = W - 2 * CELLS_PAD_X
        top = PANEL_M + CELLS_PAD_Y
        bottom = H - TEXT_ZONE
        ch = (bottom - top - (CELLS - 1) * CELL_GAP) / CELLS
        radius = 4                  # 苹果式柔和圆角（小倒角，不夸张）
        for i in range(CELLS):
            y0 = bottom - (i + 1) * ch - i * CELL_GAP
            y1 = bottom - i * ch - i * CELL_GAP
            r = round_rect(self.cv, CELLS_PAD_X, y0, CELLS_PAD_X + cw, y1,
                           radius, fill=COL_CELL_OFF, outline="", width=0)
            self.cell_rects.append(r)

        # ---------- 数值 + 单位（dB） + 版本 ----------
        self.vol_item = self.cv.create_text(
            W / 2, H - 62, text="--", fill=COL_TEXT,
            font=("Consolas", 15, "bold"))
        self.unit_item = self.cv.create_text(
            W / 2, H - 41, text="dB", fill=COL_TEXT_DIM, font=("Consolas", 9))
        self.ver_item = self.cv.create_text(
            W / 2, H - 23, text=VERSION, fill=COL_VERSION, font=("Consolas", 8))

        # ---------- 关闭按钮（悬停才显示，右上角） ----------
        self.close_item = self.cv.create_text(
            W - 11, 13, text="\u2715", fill=COL_CLOSE,
            font=("Consolas", 12), state="hidden", tags="close")
        self.cv.tag_bind("close", "<Enter>",
                         lambda e: self._close_hover(True))
        self.cv.tag_bind("close", "<Leave>",
                         lambda e: self._close_hover(False))
        self.cv.tag_bind("close", "<Button-1>",
                         lambda e: (root.destroy(), "break"))

        # ---------- 悬停显示/隐藏关闭按钮 ----------
        root.bind("<Enter>", lambda e: self._show_close(True))
        root.bind("<Leave>", lambda e: self._show_close(False))
        self.cv.bind("<Enter>", lambda e: self._show_close(True))
        self.cv.bind("<Leave>", lambda e: self._show_close(False))

        # ---------- 拖动 / 退出 ----------
        self.cv.bind("<Button-1>", self._drag_start)
        self.cv.bind("<B1-Motion>", self._drag_move)
        root.bind("<Button-1>", self._drag_start)
        root.bind("<B1-Motion>", self._drag_move)
        root.bind("<Button-3>", lambda e: root.destroy())
        root.bind("<Escape>", lambda e: root.destroy())

        # ---------- 音频流 ----------
        self.stream = sd.InputStream(
            samplerate=SAMPLE_RATE, channels=1, dtype="float32",
            blocksize=BLOCK, callback=self.audio_cb)
        self.stream.start()

        self.root.after(33, self.update_ui)

    # ---------- 悬停开关 ----------
    def _show_close(self, show):
        if self._close_after:
            try:
                self.root.after_cancel(self._close_after)
            except Exception:
                pass
            self._close_after = None
        if show:
            self.cv.itemconfig(self.close_item, state="normal")
        else:
            self._close_after = self.root.after(
                250, lambda: self.cv.itemconfig(self.close_item, state="hidden"))

    def _close_hover(self, hover):
        self.cv.itemconfig(self.close_item,
                           fill=COL_CLOSE_HOVER if hover else COL_CLOSE)

    def _drag_start(self, e):
        self._drag = (e.x_root - self.root.winfo_x(),
                      e.y_root - self.root.winfo_y())

    def _drag_move(self, e):
        if self._drag:
            self.root.geometry(
                "+%d+%d" % (e.x_root - self._drag[0],
                            e.y_root - self._drag[1]))

    # ---------- 音频 ----------
    def audio_cb(self, indata, frames, time_info, status):
        data = indata[:, 0]
        rms = float(np.sqrt(np.mean(data ** 2)))
        self.dbfs = 20.0 * np.log10(rms + 1e-12)
        target = max(0.0, min(100.0,
                     (self.dbfs - DB_MIN) / (DB_MAX - DB_MIN) * 100.0))
        self.volume = self.volume * SMOOTH + target * (1 - SMOOTH)
        self.clipping = bool(np.max(np.abs(data)) > 0.98)

    # ---------- 刷新 ----------
    def update_ui(self):
        v = self.volume
        lit = max(0, min(CELLS, int(round(v / 100.0 * CELLS))))

        for i, r in enumerate(self.cell_rects):
            if i < lit:
                self.cv.itemconfig(r, fill=level_color((i + 1) / CELLS))
            else:
                self.cv.itemconfig(r, fill=COL_CELL_OFF)

        self.cv.itemconfig(self.vol_item, text="%5.1f" % self.dbfs)
        if self.clipping or self.dbfs >= -6:
            self.cv.itemconfig(self.vol_item, fill="#ff4d4d")
        elif self.dbfs >= -10:
            self.cv.itemconfig(self.vol_item, fill="#ff7b72")
        elif self.dbfs >= -25:
            self.cv.itemconfig(self.vol_item, fill="#facc15")
        elif self.dbfs >= -45:
            self.cv.itemconfig(self.vol_item, fill="#4ade80")
        elif self.dbfs >= -60:
            self.cv.itemconfig(self.vol_item, fill="#38bdf8")
        else:
            self.cv.itemconfig(self.vol_item, fill="#45455a")

        self.root.after(33, self.update_ui)

    def close(self):
        try:
            self.stream.stop()
            self.stream.close()
        except Exception:
            pass


def main():
    root = tk.Tk()
    app = MicMeter(root)
    root.protocol("WM_DELETE_WINDOW", lambda: (app.close(), root.destroy()))
    root.mainloop()


if __name__ == "__main__":
    main()
