#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import ctypes
import os
import platform
import time
from ctypes import wintypes
from dataclasses import dataclass
from typing import List, Optional, Tuple

# 限制部分底层库线程数，避免 OCR / OpenCV 在某些机器上占用过高
os.environ.setdefault("OMP_NUM_THREADS", "1")

import cv2
import pyperclip
import numpy as np
from mss import MSS


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DEBUG_DIR = os.path.join(SCRIPT_DIR, "debug_output")


@dataclass
class SearchBoxResult:
    found: bool
    x: int
    y: int
    w: int
    h: int
    click_x: int
    click_y: int
    plus_x: int
    plus_y: int
    plus_r: int
    window_left: int
    window_top: int
    window_title: str
    score: float = 0.0

    @property
    def center(self) -> Tuple[int, int]:
        return self.click_x, self.click_y

    @property
    def box(self) -> Tuple[int, int, int, int]:
        return self.x, self.y, self.w, self.h


class WeChatSearchBoxRecognizer:
    """
    识别微信左上角搜索框。

    核心思路：
    1. 先在指定屏幕上找到微信窗口；
    2. 在微信顶部区域里寻找“+”图标；
    3. 在“+”图标左侧寻找浅灰色搜索框候选；
    4. 用搜索框里的放大镜图标做二次验证；
    5. 返回搜索框位置和点击坐标。
    """

    def __init__(
        self,
        monitor_index: int = 2,
        debug: bool = False,
        title_keyword: Optional[str] = None,
    ):
        self.monitor_index = monitor_index
        self.debug = debug
        self.title_keyword = title_keyword

        self.result: Optional[SearchBoxResult] = None
        self.window_region: Optional[dict] = None
        self.window_title: Optional[str] = None
        self.window_image: Optional[np.ndarray] = None

    # -----------------------------
    # 基础工具
    # -----------------------------
    @staticmethod
    def enable_dpi_awareness():
        if platform.system().lower() == "windows":
            try:
                ctypes.windll.shcore.SetProcessDpiAwareness(2)
            except Exception:
                try:
                    ctypes.windll.user32.SetProcessDPIAware()
                except Exception:
                    pass

    @staticmethod
    def ensure_debug_dir():
        os.makedirs(DEBUG_DIR, exist_ok=True)

    @staticmethod
    def save_image(filename: str, img: np.ndarray):
        WeChatSearchBoxRecognizer.ensure_debug_dir()
        path = os.path.join(DEBUG_DIR, filename)
        ext = os.path.splitext(path)[1]
        ok, data = cv2.imencode(ext, img)

        if ok:
            data.tofile(path)
            print(f"已保存: {path}")
        else:
            print(f"保存失败: {path}")

        return path

    @staticmethod
    def save_text(filename: str, text: str):
        WeChatSearchBoxRecognizer.ensure_debug_dir()
        path = os.path.join(DEBUG_DIR, filename)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        print(f"已保存: {path}")
        return path

    @staticmethod
    def get_monitor_region(monitor_index=2):
        with MSS() as sct:
            print("当前屏幕列表：")
            for i, m in enumerate(sct.monitors):
                print(
                    f"monitor {i}: left={m['left']}, top={m['top']}, "
                    f"width={m['width']}, height={m['height']}"
                )

            if monitor_index >= len(sct.monitors):
                raise ValueError(
                    f"monitor_index={monitor_index} 不存在，最多只能选到 {len(sct.monitors) - 1}"
                )

            return dict(sct.monitors[monitor_index])

    @staticmethod
    def screenshot_region_bgr(region):
        with MSS() as sct:
            raw = np.array(sct.grab(region))
        return cv2.cvtColor(raw, cv2.COLOR_BGRA2BGR)

    @staticmethod
    def rect_overlap_ratio(a, b):
        ax1, ay1 = a["left"], a["top"]
        ax2, ay2 = ax1 + a["width"], ay1 + a["height"]

        bx1, by1 = b["left"], b["top"]
        bx2, by2 = bx1 + b["width"], by1 + b["height"]

        ix1 = max(ax1, bx1)
        iy1 = max(ay1, by1)
        ix2 = min(ax2, bx2)
        iy2 = min(ay2, by2)

        if ix2 <= ix1 or iy2 <= iy1:
            return 0.0

        inter = (ix2 - ix1) * (iy2 - iy1)
        area = max(1, a["width"] * a["height"])
        return inter / area

    @staticmethod
    def enum_windows():
        if platform.system().lower() != "windows":
            raise RuntimeError("这个窗口枚举方法只适配 Windows")

        user32 = ctypes.windll.user32
        windows = []

        EnumWindowsProc = ctypes.WINFUNCTYPE(
            wintypes.BOOL,
            wintypes.HWND,
            wintypes.LPARAM,
        )

        def callback(hwnd, lParam):
            if not user32.IsWindowVisible(hwnd):
                return True

            try:
                if user32.IsIconic(hwnd):
                    return True
            except Exception:
                pass

            rect = wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(rect))

            left = rect.left
            top = rect.top
            right = rect.right
            bottom = rect.bottom
            width = right - left
            height = bottom - top

            if width <= 200 or height <= 200:
                return True

            length = user32.GetWindowTextLengthW(hwnd)
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buf, length + 1)
            title = buf.value

            windows.append(
                {
                    "hwnd": int(hwnd),
                    "title": title,
                    "left": int(left),
                    "top": int(top),
                    "width": int(width),
                    "height": int(height),
                }
            )
            return True

        user32.EnumWindows(EnumWindowsProc(callback), 0)
        return windows

    # -----------------------------
    # 微信窗口识别
    # -----------------------------
    def has_wechat_left_nav_icons(self, img, debug=False):
        """
        判断窗口左侧是否是微信竖向功能栏：
        - 左侧浅灰竖栏
        - 上方有绿色聊天图标
        - 中部有多个灰色功能图标
        """
        h, w = img.shape[:2]

        if w < 500 or h < 400:
            return False

        nav_w = min(62, w)
        nav = img[:, :nav_w]
        nav_mid = nav[60:min(h - 30, h), :]

        if nav_mid.size == 0:
            return False

        nav_gray = cv2.cvtColor(nav_mid, cv2.COLOR_BGR2GRAY)
        nav_hsv = cv2.cvtColor(nav_mid, cv2.COLOR_BGR2HSV)

        nav_mean = float(np.mean(nav_gray))
        nav_sat_mean = float(np.mean(nav_hsv[:, :, 1]))

        if not (145 <= nav_mean <= 245 and nav_sat_mean < 50):
            if debug:
                print(f"左侧栏灰度/饱和度不符合: mean={nav_mean:.1f}, sat={nav_sat_mean:.1f}")
            return False

        top_area = img[40:min(190, h), 0:nav_w]
        if top_area.size == 0:
            return False

        top_hsv = cv2.cvtColor(top_area, cv2.COLOR_BGR2HSV)
        green_mask = cv2.inRange(
            top_hsv,
            np.array([35, 60, 60]),
            np.array([95, 255, 255]),
        )

        contours, _ = cv2.findContours(
            green_mask,
            cv2.RETR_EXTERNAL,
            cv2.CHAIN_APPROX_SIMPLE,
        )

        has_green_chat_icon = False
        for cnt in contours:
            x, y, bw, bh = cv2.boundingRect(cnt)
            area = bw * bh
            if area < 50 or area > 1800:
                continue
            if bw < 7 or bh < 7:
                continue
            if bw > 48 or bh > 48:
                continue
            cx = x + bw // 2
            if 6 <= cx <= 55:
                has_green_chat_icon = True
                break

        if not has_green_chat_icon:
            if debug:
                print("没有找到微信左侧绿色聊天图标")
                self.save_image("debug_left_nav_top_area.png", top_area)
                self.save_image("debug_left_nav_green_mask.png", green_mask)
            return False

        icon_area = img[80:min(h - 25, h), 4:min(58, w)]
        if icon_area.size == 0:
            return False

        icon_gray = cv2.cvtColor(icon_area, cv2.COLOR_BGR2GRAY)
        dark_mask = cv2.inRange(icon_gray, 0, 175)
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
        dark_mask = cv2.morphologyEx(dark_mask, cv2.MORPH_CLOSE, kernel, iterations=1)

        contours, _ = cv2.findContours(
            dark_mask,
            cv2.RETR_EXTERNAL,
            cv2.CHAIN_APPROX_SIMPLE,
        )

        icon_centers = []
        for cnt in contours:
            x, y, bw, bh = cv2.boundingRect(cnt)
            area = bw * bh
            if area < 18 or area > 1300:
                continue
            if bw < 4 or bh < 4:
                continue
            if bw > 46 or bh > 46:
                continue
            cx = x + bw // 2
            cy = y + bh // 2
            if not (6 <= cx <= 50):
                continue
            icon_centers.append(cy + 80)

        icon_centers = sorted(icon_centers)
        merged_centers = []
        for cy in icon_centers:
            if not merged_centers:
                merged_centers.append(cy)
                continue
            if abs(cy - merged_centers[-1]) < 18:
                merged_centers[-1] = int((merged_centers[-1] + cy) / 2)
            else:
                merged_centers.append(cy)

        icon_count = len(merged_centers)

        if debug:
            print(f"微信左侧功能图标数量: {icon_count}, centers={merged_centers}")

        return icon_count >= 5

    def score_wechat_window(self, img, debug=False):
        h, w = img.shape[:2]
        if w < 650 or h < 450:
            return 0

        if not self.has_wechat_left_nav_icons(img, debug=debug):
            return 0

        score = 3000

        # 顶部搜索区域应该有较亮的背景
        top_area = img[15:min(h, 90), 60:min(w, 380)]
        if top_area.size > 0:
            gray = cv2.cvtColor(top_area, cv2.COLOR_BGR2GRAY)
            hsv = cv2.cvtColor(top_area, cv2.COLOR_BGR2HSV)
            if np.mean(gray) > 185 and np.mean(hsv[:, :, 1]) < 40:
                score += 600

        # 左边会话栏存在时，额外加分
        list_area = img[75:min(h, h - 20), 60:min(w, 320)]
        if list_area.size > 0:
            list_gray = cv2.cvtColor(list_area, cv2.COLOR_BGR2GRAY)
            if np.std(list_gray) > 15:
                score += 350

        return score

    def find_wechat_window_on_monitor(self):
        monitor = self.get_monitor_region(self.monitor_index)
        windows = self.enum_windows()

        scored = []
        for win in windows:
            overlap = self.rect_overlap_ratio(win, monitor)
            if overlap <= 0:
                continue
            if win["width"] < 600 or win["height"] < 400:
                continue
            if self.title_keyword and self.title_keyword not in win["title"]:
                continue

            region = {
                "left": win["left"],
                "top": win["top"],
                "width": win["width"],
                "height": win["height"],
            }

            try:
                img = self.screenshot_region_bgr(region)
            except Exception:
                continue

            score = self.score_wechat_window(img, debug=self.debug)
            if score <= 0:
                continue

            if self.title_keyword:
                score += 5000

            scored.append((score, win, img, region))

        scored.sort(key=lambda item: item[0], reverse=True)

        if self.debug:
            lines = []
            for score, win, _, _ in scored[:20]:
                lines.append(
                    f"score={score}, title={win['title']}, rect=({win['left']},{win['top']},{win['width']},{win['height']})"
                )
            self.save_text("debug_search_box_window_scores.txt", "\n".join(lines))

        if not scored:
            return None, None, None

        best_score, best_win, best_img, best_region = scored[0]
        print(
            f"选中的微信候选窗口: score={best_score}, title={best_win['title']}, rect=({best_region['left']}, {best_region['top']}, {best_region['width']}, {best_region['height']})"
        )

        if self.debug:
            self.save_image("debug_search_box_wechat_window.png", best_img)

        return best_img, best_region, best_win

    # -----------------------------
    # 搜索框识别
    # -----------------------------
    def find_plus_icon_candidates(self, roi: np.ndarray) -> List[Tuple[int, int, int, float]]:
        """
        在顶部区域里寻找圆形加号图标。
        返回: [(cx, cy, r, score), ...]
        """
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        blur = cv2.GaussianBlur(gray, (5, 5), 0)

        circles = cv2.HoughCircles(
            blur,
            cv2.HOUGH_GRADIENT,
            dp=1.15,
            minDist=24,
            param1=90,
            param2=18,
            minRadius=7,
            maxRadius=18,
        )

        candidates: List[Tuple[int, int, int, float]] = []
        h, w = roi.shape[:2]

        if circles is None:
            circles_arr = []
        else:
            circles_arr = np.round(circles[0]).astype(int)

        for circle in circles_arr:
            cx, cy, r = circle.tolist()

            if cx < int(w * 0.45):
                continue
            if cy < 0 or cy >= h:
                continue

            x1 = max(0, cx - r - 5)
            x2 = min(w, cx + r + 5)
            y1 = max(0, cy - r - 5)
            y2 = min(h, cy + r + 5)
            patch = gray[y1:y2, x1:x2]
            if patch.size == 0:
                continue

            dark = (patch < 165).astype(np.uint8)
            local_cx = min(patch.shape[1] - 1, cx - x1)
            local_cy = min(patch.shape[0] - 1, cy - y1)

            row = dark[max(0, local_cy - 1):min(patch.shape[0], local_cy + 2), :]
            col = dark[:, max(0, local_cx - 1):min(patch.shape[1], local_cx + 2)]

            row_dark_ratio = float(np.mean(row)) if row.size else 0.0
            col_dark_ratio = float(np.mean(col)) if col.size else 0.0
            patch_dark_ratio = float(np.mean(dark))

            score = row_dark_ratio * 2.0 + col_dark_ratio * 2.0 + patch_dark_ratio

            if row_dark_ratio < 0.18 or col_dark_ratio < 0.18:
                continue
            if patch_dark_ratio < 0.05 or patch_dark_ratio > 0.42:
                continue

            candidates.append((cx, cy, r, score))

        # 兜底：HoughCircles 对微信这个细线加号有时不稳定。
        # 如果没找到圆，就直接在右侧区域找“圆圈+加号”的深色小方块。
        if not candidates:
            dark_mask = cv2.inRange(gray, 0, 175)
            kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
            dark_mask = cv2.morphologyEx(dark_mask, cv2.MORPH_CLOSE, kernel, iterations=2)

            contours, _ = cv2.findContours(
                dark_mask,
                cv2.RETR_EXTERNAL,
                cv2.CHAIN_APPROX_SIMPLE,
            )

            for cnt in contours:
                x, y, bw, bh = cv2.boundingRect(cnt)

                if x < int(w * 0.45):
                    continue
                if bw < 10 or bh < 10:
                    continue
                if bw > 34 or bh > 34:
                    continue

                aspect = bw / max(bh, 1)
                if aspect < 0.65 or aspect > 1.55:
                    continue

                cx = x + bw // 2
                cy = y + bh // 2
                r = int(max(bw, bh) / 2)

                patch = dark_mask[max(0, cy - r - 4):min(h, cy + r + 4),
                                  max(0, cx - r - 4):min(w, cx + r + 4)]
                if patch.size == 0:
                    continue

                dark_ratio = float(np.mean(patch > 0))
                if dark_ratio < 0.06 or dark_ratio > 0.55:
                    continue

                score = 1.0 + dark_ratio
                candidates.append((cx, cy, r, score))

        candidates.sort(key=lambda item: item[3], reverse=True)
        return candidates

    def has_magnifier_icon(self, search_box_roi: np.ndarray) -> Tuple[bool, float]:
        """
        检查搜索框左侧是否像放大镜图标。
        返回: (是否通过, 分数)
        """
        h, w = search_box_roi.shape[:2]
        if h < 10 or w < 30:
            return False, 0.0

        left_w = min(w, max(24, int(w * 0.22)))
        roi = search_box_roi[:, :left_w]
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        blur = cv2.GaussianBlur(gray, (5, 5), 0)

        circles = cv2.HoughCircles(
            blur,
            cv2.HOUGH_GRADIENT,
            dp=1.2,
            minDist=12,
            param1=70,
            param2=10,
            minRadius=4,
            maxRadius=10,
        )

        dark = cv2.inRange(gray, 0, 180)
        dark_ratio = float(np.mean(dark > 0))

        score = dark_ratio

        if circles is not None:
            best_circle_score = 0.0
            for circle in np.round(circles[0]).astype(int):
                cx, cy, r = circle.tolist()
                if cx > left_w * 0.80:
                    continue
                if cy < 2 or cy >= h - 2:
                    continue

                # 放大镜的“柄”通常在圆的右下侧
                handle_x1 = min(left_w - 1, cx + r - 1)
                handle_x2 = min(left_w, cx + r + 8)
                handle_y1 = min(h - 1, cy + r - 1)
                handle_y2 = min(h, cy + r + 8)

                if handle_x2 <= handle_x1 or handle_y2 <= handle_y1:
                    continue

                handle = dark[handle_y1:handle_y2, handle_x1:handle_x2]
                handle_ratio = float(np.mean(handle > 0)) if handle.size else 0.0
                local_score = 1.0 + handle_ratio + dark_ratio
                best_circle_score = max(best_circle_score, local_score)

            score = max(score, best_circle_score)

        passed = score >= 0.38
        return passed, score

    def detect_search_box_in_window(self, img: np.ndarray) -> Optional[SearchBoxResult]:
        h, w = img.shape[:2]

        # 搜索框一般在微信窗口左上区域
        roi_x1 = 60
        roi_y1 = 12
        roi_x2 = min(w, 390)
        roi_y2 = min(h, 90)

        if roi_x2 <= roi_x1 or roi_y2 <= roi_y1:
            return None

        roi = img[roi_y1:roi_y2, roi_x1:roi_x2]
        roi_h, roi_w = roi.shape[:2]

        if self.debug:
            self.save_image("debug_search_box_top_roi.png", roi)

        plus_candidates = self.find_plus_icon_candidates(roi)
        if self.debug:
            plus_dbg = roi.copy()
            for cx, cy, r, s in plus_candidates[:10]:
                cv2.circle(plus_dbg, (cx, cy), r, (0, 255, 0), 2)
                cv2.putText(
                    plus_dbg,
                    f"{s:.2f}",
                    (cx - 12, max(10, cy - r - 4)),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.35,
                    (0, 0, 255),
                    1,
                )
            self.save_image("debug_search_box_plus_candidates.png", plus_dbg)

        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)

        # 搜索框底色是浅灰/白色，饱和度低。
        # 旧版写成 gray <= 245，遇到接近白色的搜索框会被排除，
        # 导致明明能看到搜索框，但识别不到。
        light_mask = (
            (gray >= 235) & (gray <= 255) & (hsv[:, :, 1] <= 55)
        ).astype(np.uint8) * 255

        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (7, 5))
        light_mask = cv2.morphologyEx(light_mask, cv2.MORPH_CLOSE, kernel, iterations=2)
        light_mask = cv2.morphologyEx(light_mask, cv2.MORPH_OPEN, kernel, iterations=1)

        if self.debug:
            self.save_image("debug_search_box_light_mask.png", light_mask)

        contours, _ = cv2.findContours(
            light_mask,
            cv2.RETR_EXTERNAL,
            cv2.CHAIN_APPROX_SIMPLE,
        )

        candidates = []

        for cnt in contours:
            x, y, bw, bh = cv2.boundingRect(cnt)

            if bw < 90 or bw > 280:
                continue
            if bh < 20 or bh > 52:
                continue
            if x > roi_w * 0.65:
                continue
            if y > roi_h * 0.80:
                continue

            real_x = roi_x1 + x
            real_y = roi_y1 + y
            crop = img[real_y:real_y + bh, real_x:real_x + bw]
            if crop.size == 0:
                continue

            mag_ok, mag_score = self.has_magnifier_icon(crop)

            # 搜索右侧的加号图标候选
            plus_bonus = 0.0
            chosen_plus = None
            for pcx, pcy, pr, ps in plus_candidates:
                # 需要在候选框右边，而且纵向位置接近
                if pcx <= x + bw:
                    continue
                gap = pcx - (x + bw)
                if gap > 65:
                    continue
                if abs((pcy) - (y + bh / 2)) > max(12, bh * 0.65):
                    continue

                bonus = 2.5 + ps - gap * 0.025
                if chosen_plus is None or bonus > plus_bonus:
                    plus_bonus = bonus
                    chosen_plus = (pcx, pcy, pr)

            if chosen_plus is None:
                continue

            roundness = bw / max(bh, 1)
            gray_crop = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
            light_ratio = float(np.mean(gray_crop > 205))

            score = 0.0
            score += plus_bonus
            score += mag_score * 3.0
            score += light_ratio * 2.0
            score += 1.2 if 4.0 <= roundness <= 8.5 else 0.0
            score += bw * 0.015

            if not mag_ok:
                score -= 1.2

            candidates.append(
                {
                    "x": real_x,
                    "y": real_y,
                    "w": bw,
                    "h": bh,
                    "score": score,
                    "mag_ok": mag_ok,
                    "mag_score": mag_score,
                    "plus": chosen_plus,
                }
            )

        # 兜底方案：如果浅色矩形轮廓没找到，但已经找到了右侧加号，
        # 就根据微信布局估算搜索框区域，再用放大镜图标验证。
        if not candidates and plus_candidates:
            for pcx, pcy, pr, ps in plus_candidates[:5]:
                est_x = 8
                est_w = max(90, pcx - 28 - est_x)
                est_h = 28
                est_y = int(pcy - est_h / 2)

                if est_w < 90 or est_w > 230:
                    continue
                if est_y < 0 or est_y + est_h > roi_h:
                    continue

                real_x = roi_x1 + est_x
                real_y = roi_y1 + est_y
                crop = img[real_y:real_y + est_h, real_x:real_x + est_w]
                if crop.size == 0:
                    continue

                mag_ok, mag_score = self.has_magnifier_icon(crop)

                # 兜底时放宽一点：有加号 + 搜索框大致位置正确即可。
                score = 2.0 + ps + mag_score * 3.0 + est_w * 0.012
                if not mag_ok:
                    score -= 0.5

                candidates.append(
                    {
                        "x": real_x,
                        "y": real_y,
                        "w": est_w,
                        "h": est_h,
                        "score": score,
                        "mag_ok": mag_ok,
                        "mag_score": mag_score,
                        "plus": (pcx, pcy, pr),
                    }
                )

        if self.debug:
            dbg = roi.copy()
            for item in candidates:
                x = item["x"] - roi_x1
                y = item["y"] - roi_y1
                bw = item["w"]
                bh = item["h"]
                color = (0, 255, 0) if item["mag_ok"] else (0, 165, 255)
                cv2.rectangle(dbg, (x, y), (x + bw, y + bh), color, 2)
                cv2.putText(
                    dbg,
                    f"{item['score']:.2f}",
                    (x, max(12, y - 5)),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.4,
                    (0, 0, 255),
                    1,
                )
                pcx, pcy, pr = item["plus"]
                cv2.circle(dbg, (pcx, pcy), pr, (255, 0, 0), 2)
            self.save_image("debug_search_box_candidates.png", dbg)

        if not candidates:
            return None

        candidates.sort(key=lambda item: item["score"], reverse=True)
        best = candidates[0]
        plus_x, plus_y, plus_r = best["plus"]

        click_x = best["x"] + best["w"] // 2
        click_y = best["y"] + best["h"] // 2

        result = SearchBoxResult(
            found=True,
            x=int(best["x"]),
            y=int(best["y"]),
            w=int(best["w"]),
            h=int(best["h"]),
            click_x=int(self.window_region["left"] + click_x),
            click_y=int(self.window_region["top"] + click_y),
            plus_x=int(self.window_region["left"] + roi_x1 + plus_x),
            plus_y=int(self.window_region["top"] + roi_y1 + plus_y),
            plus_r=int(plus_r),
            window_left=int(self.window_region["left"]),
            window_top=int(self.window_region["top"]),
            window_title=str(self.window_title or ""),
            score=float(best["score"]),
        )

        if self.debug:
            dbg = img.copy()
            cv2.rectangle(dbg, (result.x, result.y), (result.x + result.w, result.y + result.h), (0, 255, 0), 2)
            cv2.circle(dbg, (roi_x1 + plus_x, roi_y1 + plus_y), plus_r, (255, 0, 0), 2)
            cv2.putText(
                dbg,
                "wechat search box",
                (result.x, max(20, result.y - 8)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                (0, 255, 0),
                2,
            )
            self.save_image("debug_search_box_result.png", dbg)

        return result

    # -----------------------------
    # 对外接口
    # -----------------------------
    def refresh(self) -> Optional[SearchBoxResult]:
        self.enable_dpi_awareness()

        img, region, win = self.find_wechat_window_on_monitor()
        if img is None:
            print("没有找到微信窗口。请确认微信在目标屏幕上可见，且没有被完全挡住。")
            self.result = None
            return None

        self.window_image = img
        self.window_region = region
        self.window_title = win["title"] if win else None

        self.result = self.detect_search_box_in_window(img)

        if self.result is None:
            print("没有识别到微信搜索框，所以不会点击。可以加 --debug 查看调试图。")
        else:
            print(
                f"识别到搜索框: x={self.result.x}, y={self.result.y}, w={self.result.w}, h={self.result.h}, click=({self.result.click_x}, {self.result.click_y}), score={self.result.score:.2f}"
            )

        return self.result

    def get_result(self) -> Optional[SearchBoxResult]:
        return self.result

    @staticmethod
    def click_screen_position(x: int, y: int):
        user32 = ctypes.windll.user32
        user32.SetCursorPos(int(x), int(y))
        time.sleep(0.05)
        user32.mouse_event(0x0002, 0, 0, 0, 0)  # left down
        time.sleep(0.05)
        user32.mouse_event(0x0004, 0, 0, 0, 0)  # left up

    def click_search_box(self) -> bool:
        if self.result is None:
            return False
        self.click_screen_position(self.result.click_x, self.result.click_y)
        return True

    def refresh_and_click(self) -> Optional[SearchBoxResult]:
        """
        对外调用方法：重新识别搜索框；如果识别到了，就自动点击。
        """
        result = self.refresh()
        if result is not None:
            self.click_search_box()
            print("已点击搜索框。")
        return result

    def paste_text_to_search_box(self, text: str = "ウィーエト", clear_first: bool = True) -> bool:
        """
        对外调用方法：把指定文字粘贴到微信左上角搜索框。

        流程：
            1. 识别搜索框；
            2. 点击搜索框；
            3. 可选：Ctrl+A 清空原内容；
            4. 把 text 写入剪贴板；
            5. Ctrl+V 粘贴。
        """
        result = self.refresh()
        if result is None:
            print("没有识别到搜索框，无法粘贴。")
            return False

        self.click_search_box()
        time.sleep(0.2)

        if clear_first:
            self.press_ctrl_a()
            time.sleep(0.08)

        pyperclip.copy(text)
        time.sleep(0.08)
        self.press_ctrl_v()

        print(f"已粘贴到搜索框: {text}")
        return True

    def paste_text_and_click_first_result(
        self,
        text: str = "ウィーエト",
        clear_first: bool = True,
        result_offset_x: int = 0,
        result_offset_y: int = 78,
        wait_after_paste: float = 0.8,
    ) -> bool:
        """
        对外调用方法：粘贴搜索关键词后，直接点击搜索框下方第一个联系人结果。

        注意：
            这里不会再用 OpenCV 识别搜索结果。
            它只根据搜索框中心坐标做固定偏移：
                click_x = search_box_click_x + result_offset_x
                click_y = search_box_click_y + result_offset_y

        默认 result_offset_y=78，适配微信搜索框下方第一个联系人结果。
        """
        result = self.refresh()
        if result is None:
            print("没有识别到搜索框，无法粘贴和点击第一个结果。")
            return False

        self.click_search_box()
        time.sleep(0.2)

        if clear_first:
            self.press_ctrl_a()
            time.sleep(0.08)

        pyperclip.copy(text)
        time.sleep(0.08)
        self.press_ctrl_v()

        print(f"已粘贴到搜索框: {text}")

        time.sleep(wait_after_paste)

        first_x = int(result.click_x + result_offset_x)
        first_y = int(result.click_y + result_offset_y)

        print(
            f"准备点击搜索框下方第一个结果: "
            f"x={first_x}, y={first_y}, "
            f"offset=({result_offset_x}, {result_offset_y})"
        )

        self.click_screen_position(first_x, first_y)
        print("已点击第一个搜索结果。")
        return True

    @staticmethod
    def keybd_event_vk(vk_code: int, down: bool = True):
        flags = 0 if down else 0x0002  # KEYEVENTF_KEYUP
        ctypes.windll.user32.keybd_event(vk_code, 0, flags, 0)

    @classmethod
    def press_ctrl_a(cls):
        VK_CONTROL = 0x11
        VK_A = 0x41
        cls.keybd_event_vk(VK_CONTROL, True)
        time.sleep(0.02)
        cls.keybd_event_vk(VK_A, True)
        time.sleep(0.02)
        cls.keybd_event_vk(VK_A, False)
        time.sleep(0.02)
        cls.keybd_event_vk(VK_CONTROL, False)

    @classmethod
    def press_ctrl_v(cls):
        VK_CONTROL = 0x11
        VK_V = 0x56
        cls.keybd_event_vk(VK_CONTROL, True)
        time.sleep(0.02)
        cls.keybd_event_vk(VK_V, True)
        time.sleep(0.02)
        cls.keybd_event_vk(VK_V, False)
        time.sleep(0.02)
        cls.keybd_event_vk(VK_CONTROL, False)


def main():
    parser = argparse.ArgumentParser(description="识别微信左上角搜索框，粘贴文字，并固定偏移点击第一个搜索结果")
    parser.add_argument(
        "--monitor",
        type=int,
        default=2,
        help="截图屏幕：0=所有屏幕，1=主屏，2=副屏",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="保存调试图片",
    )
    parser.add_argument(
        "--title-keyword",
        default=None,
        help="可选：窗口标题关键词，比如 微信",
    )
    parser.add_argument(
        "--text",
        "-t",
        default="ウィーエト",
        help="要粘贴到微信搜索框的文字",
    )
    parser.add_argument(
        "--no-paste",
        action="store_true",
        help="只识别，不点击、不粘贴",
    )
    parser.add_argument(
        "--no-result-click",
        action="store_true",
        help="只粘贴到搜索框，不点击下方第一个搜索结果",
    )
    parser.add_argument(
        "--result-offset-x",
        type=int,
        default=0,
        help="第一个搜索结果点击点相对搜索框中心的 X 偏移，默认 0",
    )
    parser.add_argument(
        "--result-offset-y",
        type=int,
        default=78,
        help="第一个搜索结果点击点相对搜索框中心的 Y 偏移，默认 78",
    )
    parser.add_argument(
        "--wait-after-paste",
        type=float,
        default=0.8,
        help="粘贴后等待搜索结果出现的秒数，默认 0.8",
    )

    args = parser.parse_args()

    print("3 秒后开始识别。微信不需要获得焦点，但必须在目标屏幕上可见，不能被完全遮挡。")
    time.sleep(3)

    recognizer = WeChatSearchBoxRecognizer(
        monitor_index=args.monitor,
        debug=args.debug,
        title_keyword=args.title_keyword,
    )

    result = recognizer.refresh()

    if result is None:
        return

    print()
    print("最终结果：")
    print(f"window_title = {result.window_title}")
    print(f"box = ({result.x}, {result.y}, {result.w}, {result.h})")
    print(f"click = ({result.click_x}, {result.click_y})")
    print(f"plus = ({result.plus_x}, {result.plus_y}), r={result.plus_r}")
    print(f"score = {result.score:.2f}")

    # 默认：识别到了就点击搜索框，粘贴指定文字，然后点击搜索框下方第一个结果
    if not args.no_paste:
        if args.no_result_click:
            recognizer.click_search_box()
            time.sleep(0.2)
            recognizer.press_ctrl_a()
            time.sleep(0.08)
            pyperclip.copy(args.text)
            time.sleep(0.08)
            recognizer.press_ctrl_v()
            print(f"已粘贴到搜索框: {args.text}")
        else:
            # 不再识别搜索结果，直接根据搜索框坐标向下固定偏移点击第一个联系人结果
            first_x = int(result.click_x + args.result_offset_x)
            first_y = int(result.click_y + args.result_offset_y)

            recognizer.click_search_box()
            time.sleep(0.2)
            recognizer.press_ctrl_a()
            time.sleep(0.08)
            pyperclip.copy(args.text)
            time.sleep(0.08)
            recognizer.press_ctrl_v()
            print(f"已粘贴到搜索框: {args.text}")

            time.sleep(args.wait_after_paste)

            print(
                f"准备点击搜索框下方第一个结果: "
                f"x={first_x}, y={first_y}, "
                f"offset=({args.result_offset_x}, {args.result_offset_y})"
            )
            recognizer.click_screen_position(first_x, first_y)
            print("已点击第一个搜索结果。")


if __name__ == "__main__":
    main()
