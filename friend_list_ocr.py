#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
微信好友/会话列表识别器。

用法一：直接运行
    python wechat_friend_list_recognizer.py --monitor 2 --debug

用法二：在其他 Python 文件中调用
    from wechat_friend_list_recognizer import WeChatFriendListRecognizer

    recognizer = WeChatFriendListRecognizer(monitor_index=2, debug=False)
    recognizer.refresh()

    for friend in recognizer.results:
        print(friend.index, friend.name, friend.click_x, friend.click_y, friend.raw_texts)

说明：
    - results 是识别结果属性。
    - refresh() 会重新截图、切图、OCR，并刷新 results。
    - 默认 keep_all_rows=True，即使 OCR 名字不准，也会保留每一行的位置。
"""

import argparse
import ctypes
import os
import platform
import time
from ctypes import wintypes
from dataclasses import dataclass, field
from typing import Any, List, Optional, Tuple

# 限制部分底层库的线程数，避免 OCR 初始化/推理时占用过高
os.environ["OMP_NUM_THREADS"] = "1"

import cv2
import numpy as np
from mss import MSS


@dataclass
class FriendPosition:
    """一条微信会话/好友行的位置和识别结果。"""

    index: int
    name: str
    x: int
    y: int
    w: int
    h: int
    click_x: int
    click_y: int
    raw_texts: List[Tuple[str, float]] = field(default_factory=list)
    raw_name: str = ""
    best_score: float = 0.0
    is_valid_name: bool = False

    @property
    def center(self) -> Tuple[int, int]:
        """点击中心坐标，屏幕绝对坐标。"""
        return self.click_x, self.click_y

    @property
    def box(self) -> Tuple[int, int, int, int]:
        """行区域，微信窗口内部坐标。"""
        return self.x, self.y, self.w, self.h

    def to_dict(self) -> dict:
        """需要序列化时再手动调用，不会自动保存 JSON。"""
        return {
            "index": self.index,
            "name": self.name,
            "x": self.x,
            "y": self.y,
            "w": self.w,
            "h": self.h,
            "click_x": self.click_x,
            "click_y": self.click_y,
            "raw_texts": self.raw_texts,
            "raw_name": self.raw_name,
            "best_score": self.best_score,
            "is_valid_name": self.is_valid_name,
        }


class WeChatFriendListRecognizer:
    """
    微信好友/会话列表识别器。

    对外主要用：
        recognizer = WeChatFriendListRecognizer()
        recognizer.refresh()
        recognizer.results
    """

    def __init__(
        self,
        monitor_index: int = 2,
        debug: bool = False,
        row_height: int = 72,
        title_keyword: Optional[str] = None,
        score_threshold: float = 0.20,
        keep_all_rows: bool = True,
        debug_dir: Optional[str] = None,
    ):
        self.monitor_index = monitor_index
        self.debug = debug
        self.row_height = row_height
        self.title_keyword = title_keyword
        self.score_threshold = score_threshold
        self.keep_all_rows = keep_all_rows

        self.script_dir = os.path.dirname(os.path.abspath(__file__))
        self.debug_dir = debug_dir or os.path.join(self.script_dir, "debug_output")

        self._results: List[FriendPosition] = []
        self._ocr_engine = None
        self._last_window_img = None
        self._last_window_region = None
        self._last_window_info = None
        self._last_rows: List[Tuple[int, int, int, int]] = []

    @property
    def results(self) -> List[FriendPosition]:
        """最近一次 refresh() 得到的识别结果。"""
        return self._results

    @property
    def last_window_img(self):
        """最近一次识别时截到的微信窗口图。"""
        return self._last_window_img

    @property
    def last_window_region(self):
        """最近一次识别到的微信窗口屏幕区域。"""
        return self._last_window_region

    @property
    def last_rows(self) -> List[Tuple[int, int, int, int]]:
        """最近一次识别到的候选行，坐标是微信窗口内部坐标。"""
        return self._last_rows

    def refresh(self) -> List[FriendPosition]:
        """
        重新截图、识别，并刷新 self.results。
        """
        self.enable_dpi_awareness()

        img, region, win = self.find_wechat_window_on_monitor()

        self._last_window_img = img
        self._last_window_region = region
        self._last_window_info = win
        self._last_rows = []
        self._results = []

        if img is None or region is None:
            print("没有找到微信窗口。请确认微信在指定屏幕上可见，且没有被完全遮挡。")
            return self._results

        centers = self.find_avatar_centers_in_wechat_window(
            img,
            prefix="final",
        )
        print(f"头像中心数量: {len(centers)} -> {centers}")

        rows = self.build_rows_from_avatar_centers(img, centers)

        if len(rows) < 3:
            selected_center = self.find_selected_row_center_in_list(img)
            if selected_center is not None:
                print(f"使用绿色选中行兜底，中心 y={selected_center}")
                rows = self.build_rows_from_selected_center(img, selected_center)

        self._last_rows = rows
        print(f"候选会话行数量: {len(rows)}")

        if not rows:
            print("没有生成好友/会话行。建议加 --debug 看调试图。")
            return self._results

        ocr_engine = self.get_ocr_engine()
        screen_left = region["left"]
        screen_top = region["top"]
        result_img = img.copy()

        friends: List[FriendPosition] = []

        for i, row in enumerate(rows):
            name, raw_texts, raw_name, best_score = self.ocr_name_from_row(
                ocr_engine,
                img,
                row,
                index=i,
            )

            valid = self.is_valid_friend_name(name)
            print(f"第 {i} 行 OCR: {raw_texts} -> name={name}")

            if not valid:
                if not self.keep_all_rows:
                    continue
                name = ""

            rx, ry, rw, rh = row
            click_x = int(screen_left + rx + rw // 2)
            click_y = int(screen_top + ry + rh // 2)

            friend = FriendPosition(
                index=i,
                name=name,
                x=int(rx),
                y=int(ry),
                w=int(rw),
                h=int(rh),
                click_x=click_x,
                click_y=click_y,
                raw_texts=raw_texts,
                raw_name=raw_name,
                best_score=best_score,
                is_valid_name=valid,
            )
            friends.append(friend)

            cv2.rectangle(result_img, (rx, ry), (rx + rw, ry + rh), (0, 255, 0), 2)
            cv2.putText(
                result_img,
                str(len(friends) - 1),
                (rx + 5, ry + 25),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.8,
                (0, 0, 255),
                2,
            )

        self.save_image("debug_friend_ocr_result.png", result_img)

        self._results = friends
        self.print_results()
        return self._results

    def print_results(self) -> None:
        print()
        print("识别结果：")

        for idx, friend in enumerate(self._results):
            name_show = friend.name if friend.name else "<未识别/低置信>"
            print(
                f"{idx}. 原始行号={friend.index} "
                f"名字={name_show} "
                f"位置=({friend.x}, {friend.y}, {friend.w}, {friend.h}) "
                f"点击坐标=({friend.click_x}, {friend.click_y}) "
                f"best_score={friend.best_score:.4f} "
                f"raw_name={friend.raw_name}"
            )

    def get_result_by_name(self, name: str, exact: bool = True) -> Optional[FriendPosition]:
        """按名字查找最近一次识别结果。"""
        for friend in self._results:
            if exact:
                if friend.name == name:
                    return friend
            else:
                if name and name in friend.name:
                    return friend
        return None

    # ------------------------------------------------------------------
    # 基础工具
    # ------------------------------------------------------------------

    @staticmethod
    def enable_dpi_awareness() -> None:
        if platform.system().lower() == "windows":
            try:
                ctypes.windll.shcore.SetProcessDpiAwareness(2)
            except Exception:
                try:
                    ctypes.windll.user32.SetProcessDPIAware()
                except Exception:
                    pass

    def ensure_debug_dir(self) -> None:
        os.makedirs(self.debug_dir, exist_ok=True)

    def save_image(self, filename: str, img) -> str:
        self.ensure_debug_dir()
        path = os.path.join(self.debug_dir, filename)

        ext = os.path.splitext(path)[1]
        ok, data = cv2.imencode(ext, img)

        if ok:
            data.tofile(path)
            print(f"已保存: {path}")
        else:
            print(f"保存失败: {path}")

        return path

    def save_text(self, filename: str, text: str) -> str:
        self.ensure_debug_dir()
        path = os.path.join(self.debug_dir, filename)

        with open(path, "w", encoding="utf-8") as f:
            f.write(text)

        print(f"已保存: {path}")
        return path

    @staticmethod
    def screenshot_region_bgr(region: dict):
        with MSS() as sct:
            raw = np.array(sct.grab(region))

        img = cv2.cvtColor(raw, cv2.COLOR_BGRA2BGR)
        return img

    @staticmethod
    def rect_overlap_ratio(a: dict, b: dict) -> float:
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

    def get_monitor_region(self) -> dict:
        with MSS() as sct:
            print("当前屏幕列表：")
            for i, m in enumerate(sct.monitors):
                print(
                    f"monitor {i}: "
                    f"left={m['left']}, top={m['top']}, "
                    f"width={m['width']}, height={m['height']}"
                )

            if self.monitor_index >= len(sct.monitors):
                raise ValueError(
                    f"monitor_index={self.monitor_index} 不存在，最多只能选到 {len(sct.monitors) - 1}"
                )

            return dict(sct.monitors[self.monitor_index])

    @staticmethod
    def enum_windows() -> List[dict]:
        """枚举当前 Windows 可见窗口。"""
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

    # ------------------------------------------------------------------
    # 微信窗口定位
    # ------------------------------------------------------------------

    def has_wechat_left_nav_icons(self, img) -> bool:
        """
        判断窗口左侧是否是微信的竖向功能栏。
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
            if self.debug:
                print(f"左侧栏灰度/饱和度不符合: mean={nav_mean:.1f}, sat={nav_sat_mean:.1f}")
            return False

        top_area = img[40:min(190, h), 0:nav_w]

        if top_area.size == 0:
            return False

        top_hsv = cv2.cvtColor(top_area, cv2.COLOR_BGR2HSV)

        lower_green = np.array([35, 60, 60])
        upper_green = np.array([95, 255, 255])
        green_mask = cv2.inRange(top_hsv, lower_green, upper_green)

        green_contours, _ = cv2.findContours(
            green_mask,
            cv2.RETR_EXTERNAL,
            cv2.CHAIN_APPROX_SIMPLE,
        )

        has_green_chat_icon = False

        for cnt in green_contours:
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
            if self.debug:
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

        if self.debug:
            print(f"微信左侧功能图标数量: {icon_count}, centers={merged_centers}")
            debug_nav = img.copy()
            cv2.rectangle(debug_nav, (0, 0), (nav_w, h), (0, 255, 0), 2)

            for cy in merged_centers:
                cv2.circle(debug_nav, (30, int(cy)), 8, (0, 0, 255), 2)

            self.save_image("debug_wechat_left_nav_check.png", debug_nav)
            self.save_image("debug_left_nav_dark_mask.png", dark_mask)

        return icon_count >= 5

    def score_wechat_window(self, img) -> int:
        """判断一个窗口截图像不像微信窗口。"""
        h, w = img.shape[:2]

        if w < 650 or h < 450:
            return 0

        if not self.has_wechat_left_nav_icons(img):
            return 0

        score = 3000

        nav = img[min(h - 1, 80):max(81, h - 30), 0:min(60, w)]

        if nav.size > 0:
            nav_gray = cv2.cvtColor(nav, cv2.COLOR_BGR2GRAY)
            nav_hsv = cv2.cvtColor(nav, cv2.COLOR_BGR2HSV)

            nav_sat_mean = float(np.mean(nav_hsv[:, :, 1]))
            nav_mean = float(np.mean(nav_gray))
            nav_std = float(np.std(nav_gray))

            if nav_sat_mean < 35 and 130 < nav_mean < 245:
                score += 300
            if nav_std > 10:
                score += 150

        if h > 90 and w > 90:
            top_avatar = img[25:75, 10:60]
            top_gray = cv2.cvtColor(top_avatar, cv2.COLOR_BGR2GRAY)
            top_hsv = cv2.cvtColor(top_avatar, cv2.COLOR_BGR2HSV)

            if np.std(top_gray) > 18 or np.mean(top_hsv[:, :, 1]) > 25:
                score += 250

        if h > 80 and w > 260:
            search_roi = img[35:70, 70:250]
            search_gray = cv2.cvtColor(search_roi, cv2.COLOR_BGR2GRAY)
            search_hsv = cv2.cvtColor(search_roi, cv2.COLOR_BGR2HSV)

            if np.mean(search_gray) > 200 and np.mean(search_hsv[:, :, 1]) < 45:
                score += 350

        centers = self.find_avatar_centers_in_wechat_window(img)
        score += len(centers) * 500

        if len(centers) >= 3:
            gaps = np.diff(sorted(centers))
            valid_gaps = [g for g in gaps if 45 <= g <= 95]

            if len(valid_gaps) >= 2:
                score += 500

        return score

    def find_wechat_window_on_monitor(self):
        """在指定显示器上寻找微信窗口。不要求微信 focus。"""
        monitor = self.get_monitor_region()
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

            score = self.score_wechat_window(img)

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
                    f"score={score}, title={win['title']}, "
                    f"rect=({win['left']},{win['top']},{win['width']},{win['height']})"
                )
            self.save_text("debug_window_scores.txt", "\n".join(lines))

        if not scored:
            return None, None, None

        best_score, best_win, best_img, best_region = scored[0]

        print(
            f"选中的微信候选窗口: score={best_score}, title={best_win['title']}, "
            f"rect=({best_region['left']}, {best_region['top']}, "
            f"{best_region['width']}, {best_region['height']})"
        )

        if best_score < 1200:
            print("微信窗口候选分数太低，可能没找到微信。可以加 --debug 查看 debug_window_scores.txt")
            return None, None, None

        if self.debug:
            self.save_image("debug_wechat_window_screenshot.png", best_img)

        return best_img, best_region, best_win

    # ------------------------------------------------------------------
    # 会话行定位
    # ------------------------------------------------------------------

    def find_avatar_centers_in_wechat_window(self, img, prefix: str = "wechat") -> List[int]:
        """在微信窗口内部找左侧会话列表头像中心。"""
        h, w = img.shape[:2]

        avatar_x1 = 65
        avatar_x2 = min(w, 135)
        y1 = 75
        y2 = h

        if avatar_x2 <= avatar_x1 or y2 <= y1:
            return []

        roi = img[y1:y2, avatar_x1:avatar_x2]

        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)

        sat = hsv[:, :, 1]
        val = hsv[:, :, 2]

        color_mask = ((sat > 22) & (val > 30) & (val < 255)).astype(np.uint8) * 255
        dark_mask = (gray < 210).astype(np.uint8) * 255

        edges = cv2.Canny(gray, 35, 110)
        edges = cv2.dilate(
            edges,
            cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3)),
            iterations=1,
        )

        mask = cv2.bitwise_or(color_mask, dark_mask)
        mask = cv2.bitwise_or(mask, edges)

        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (7, 5))
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=1)

        if self.debug:
            self.save_image(f"debug_{prefix}_avatar_column_roi.png", roi)
            self.save_image(f"debug_{prefix}_avatar_column_mask.png", mask)

        projection = np.sum(mask > 0, axis=1)

        if len(projection) >= 9:
            smooth = np.convolve(projection, np.ones(9) / 9, mode="same")
        else:
            smooth = projection

        max_val = np.max(smooth) if len(smooth) else 0

        if max_val <= 0:
            return []

        threshold = max(8, max_val * 0.22)

        segments = []
        in_seg = False
        start = 0

        for i, val in enumerate(smooth):
            if val > threshold and not in_seg:
                start = i
                in_seg = True
            elif val <= threshold and in_seg:
                end = i
                in_seg = False

                if 18 <= end - start <= 75:
                    segments.append((start, end))

        if in_seg:
            end = len(smooth) - 1
            if 18 <= end - start <= 75:
                segments.append((start, end))

        centers = []

        for sy, ey in segments:
            cy = y1 + (sy + ey) // 2

            if cy < 80 or cy > h - 30:
                continue

            if not centers:
                centers.append(cy)
                continue

            if abs(cy - centers[-1]) < 30:
                centers[-1] = int((centers[-1] + cy) / 2)
            else:
                centers.append(cy)

        return centers

    def find_selected_row_center_in_list(self, img) -> Optional[int]:
        """兜底：只在微信窗口内部左侧会话列表区域找绿色选中行。"""
        h, w = img.shape[:2]

        x1 = 60
        x2 = min(w, 340)
        y1 = 75
        y2 = h

        roi = img[y1:y2, x1:x2]
        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)

        lower_green = np.array([35, 45, 50])
        upper_green = np.array([95, 255, 255])
        mask = cv2.inRange(hsv, lower_green, upper_green)

        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (9, 9))
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)

        if self.debug:
            self.save_image("debug_selected_row_green_mask_in_list.png", mask)

        contours, _ = cv2.findContours(
            mask,
            cv2.RETR_EXTERNAL,
            cv2.CHAIN_APPROX_SIMPLE,
        )

        candidates = []

        for cnt in contours:
            x, y, bw, bh = cv2.boundingRect(cnt)
            real_x = x + x1
            real_y = y + y1

            if bw < 160 or bw > 300:
                continue
            if bh < 35 or bh > 90:
                continue

            aspect = bw / max(bh, 1)
            if aspect < 2.2 or aspect > 8:
                continue

            candidates.append((bw * bh, real_x, real_y, bw, bh))

        if not candidates:
            return None

        candidates.sort(reverse=True)
        _, x, y, bw, bh = candidates[0]

        if self.debug:
            dbg = img.copy()
            cv2.rectangle(dbg, (x, y), (x + bw, y + bh), (0, 255, 0), 2)
            self.save_image("debug_selected_row_in_list.png", dbg)

        return y + bh // 2

    def build_rows_from_avatar_centers(
        self,
        img,
        centers: List[int],
    ) -> List[Tuple[int, int, int, int]]:
        """根据头像中心生成会话行。坐标是微信窗口内部坐标。"""
        h, w = img.shape[:2]

        list_x = 60
        list_w = min(290, w - list_x)
        rows = []

        centers = sorted(centers)

        for cy in centers:
            row_y = int(cy - self.row_height // 2)

            if row_y < 75:
                row_y = 75
            if row_y + self.row_height > h:
                continue

            rows.append((list_x, row_y, list_w, self.row_height))

        final_rows = []

        for row in rows:
            _, y, _, _ = row

            if not final_rows:
                final_rows.append(row)
                continue

            _, old_y, _, _ = final_rows[-1]

            if abs(y - old_y) < self.row_height * 0.45:
                continue

            final_rows.append(row)

        if self.debug:
            dbg = img.copy()

            for idx, (x, y, bw, bh) in enumerate(final_rows):
                cv2.rectangle(dbg, (x, y), (x + bw, y + bh), (0, 255, 0), 2)
                cv2.putText(
                    dbg,
                    str(idx),
                    (x + 5, y + 25),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.8,
                    (0, 0, 255),
                    2,
                )

            self.save_image("debug_friend_rows.png", dbg)

        return final_rows

    def build_rows_from_selected_center(
        self,
        img,
        selected_center: int,
    ) -> List[Tuple[int, int, int, int]]:
        """如果头像识别太少，用绿色选中行中心推断整列。"""
        h, w = img.shape[:2]

        list_x = 60
        list_w = min(290, w - list_x)
        rows = []

        start = selected_center

        while start - self.row_height >= 75:
            start -= self.row_height

        cur = start

        while cur + self.row_height // 2 < h:
            row_y = int(cur - self.row_height // 2)

            if row_y >= 75 and row_y + self.row_height <= h:
                rows.append((list_x, row_y, list_w, self.row_height))

            cur += self.row_height

        if self.debug:
            dbg = img.copy()

            for idx, (x, y, bw, bh) in enumerate(rows):
                cv2.rectangle(dbg, (x, y), (x + bw, y + bh), (0, 255, 255), 2)
                cv2.putText(
                    dbg,
                    str(idx),
                    (x + 5, y + 25),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.8,
                    (0, 0, 255),
                    2,
                )

            self.save_image("debug_friend_rows_from_selected.png", dbg)

        return rows

    # ------------------------------------------------------------------
    # OCR
    # ------------------------------------------------------------------

    def get_ocr_engine(self):
        if self._ocr_engine is None:
            self._ocr_engine = self.init_ocr()
        return self._ocr_engine

    @staticmethod
    def init_ocr():
        """
        初始化 CnOCR。

        安装：
            D:/sync/pythonCode/opencvTest/.venv/Scripts/python.exe -m pip install cnocr
        """
        try:
            from cnocr import CnOcr
        except ImportError as e:
            raise RuntimeError(
                "缺少 cnocr，请先安装：\n"
                "D:\\sync\\pythonCode\\opencvTest\\.venv\\Scripts\\python.exe -m pip install cnocr\n\n"
                f"原始错误：{e}"
            )

        return CnOcr()

    def collect_cnocr_texts(self, obj: Any, out: List[Tuple[str, float]], visited=None) -> None:
        """兼容解析 CnOCR 不同版本的返回结果。"""
        if visited is None:
            visited = set()

        if obj is None:
            return

        obj_id = id(obj)
        if obj_id in visited:
            return
        visited.add(obj_id)

        if isinstance(obj, dict):
            text = obj.get("text") or obj.get("rec_text") or obj.get("label")
            score = obj.get("score") or obj.get("rec_score") or obj.get("prob") or 1.0

            if text is not None:
                text = str(text).strip()
                try:
                    score = float(score)
                except Exception:
                    score = 1.0

                if text:
                    out.append((text, score))

            for key in ["res", "result", "results", "data"]:
                if key in obj:
                    self.collect_cnocr_texts(obj[key], out, visited)

            for value in obj.values():
                if isinstance(value, (dict, list, tuple)):
                    self.collect_cnocr_texts(value, out, visited)

            return

        if isinstance(obj, (list, tuple)):
            if len(obj) >= 2 and isinstance(obj[0], str):
                text = obj[0].strip()
                try:
                    score = float(obj[1])
                except Exception:
                    score = 1.0
                if text:
                    out.append((text, score))
                return

            for item in obj:
                self.collect_cnocr_texts(item, out, visited)

    def run_ocr(self, ocr_engine, image_path: str):
        """使用 CnOCR 识别单行昵称。"""
        raw_result = None

        try:
            if hasattr(ocr_engine, "ocr_for_single_line"):
                raw_result = ocr_engine.ocr_for_single_line(image_path)
            else:
                raw_result = ocr_engine.ocr(image_path)
        except Exception as e:
            print(f"CnOCR 单行识别失败，尝试普通 ocr(): {e}")
            try:
                raw_result = ocr_engine.ocr(image_path)
            except Exception as e2:
                print(f"CnOCR ocr() 调用失败: {e2}")
                return [], None

        texts = []
        self.collect_cnocr_texts(raw_result, texts)
        return texts, raw_result

    @staticmethod
    def clean_name_text(text: str) -> str:
        if not text:
            return ""

        text = str(text)

        for ch in [" ", "\n", "\r", "\t"]:
            text = text.replace(ch, "")

        for bad in ["|", "丨", "。", ".", "·", "：", ":", "_", "-", "一"]:
            while text.startswith(bad):
                text = text[1:]

        return text.strip()

    @staticmethod
    def is_valid_friend_name(name: str) -> bool:
        if not name:
            return False

        ignore_words = {
            "搜索",
            "微信",
            "通讯录",
            "聊天",
            "文件",
        }

        if name in ignore_words:
            return False

        if len(name) > 35:
            return False

        return True

    def ocr_name_from_row(
        self,
        ocr_engine,
        img,
        row_box: Tuple[int, int, int, int],
        index: int = 0,
    ) -> Tuple[str, List[Tuple[str, float]], str, float]:
        """
        从一行会话中裁出昵称并 OCR。

        返回：
            name: 通过 score_threshold 过滤后的名字。可能为空。
            texts: OCR 原始文本和分数。
            raw_name: 不按分数过滤时拼出来的原始名字。
            best_score: 这一行 OCR 的最高分。
        """
        x, y, w, h = row_box
        img_h, img_w = img.shape[:2]

        # 这里仍然沿用你当前版本的裁剪区域；后续要提升准确度可以只改这里。
        name_x1 = x + 62
        name_x2 = min(img_w, x + w - 58)

        name_y1 = y + 7
        name_y2 = min(img_h, y + 36)

        if name_x2 <= name_x1 or name_y2 <= name_y1:
            return "", [], "", 0.0

        name_roi = img[name_y1:name_y2, name_x1:name_x2]
        raw_roi_path = self.save_image(f"ocr_name_raw_{index:02d}.png", name_roi)

        name_roi_big = cv2.resize(
            name_roi,
            None,
            fx=3,
            fy=3,
            interpolation=cv2.INTER_CUBIC,
        )

        name_roi_big = cv2.copyMakeBorder(
            name_roi_big,
            10,
            10,
            10,
            10,
            cv2.BORDER_CONSTANT,
            value=(255, 255, 255),
        )

        ocr_input_path = self.save_image(f"ocr_name_input_{index:02d}.png", name_roi_big)

        texts, raw_result = self.run_ocr(
            ocr_engine,
            image_path=ocr_input_path,
        )

        self.save_text(
            f"ocr_name_result_{index:02d}.txt",
            "raw roi path:\n"
            + raw_roi_path
            + "\n\nocr input path:\n"
            + ocr_input_path
            + "\n\nraw result:\n"
            + repr(raw_result)
            + "\n\nparsed texts:\n"
            + repr(texts),
        )

        raw_parts = []
        valid_parts = []
        best_score = 0.0

        for text, score in texts:
            cleaned = self.clean_name_text(text)
            if not cleaned:
                continue

            try:
                score = float(score)
            except Exception:
                score = 0.0

            best_score = max(best_score, score)
            raw_parts.append(cleaned)

            if score >= self.score_threshold:
                valid_parts.append(cleaned)

        raw_name = self.clean_name_text("".join(raw_parts))
        name = self.clean_name_text("".join(valid_parts))

        return name, texts, raw_name, best_score


# 可选：保留一个简单函数接口，方便别的文件直接调用。
def get_friend_positions(
    monitor_index: int = 2,
    debug: bool = False,
    row_height: int = 72,
    title_keyword: Optional[str] = None,
    keep_all_rows: bool = True,
) -> List[FriendPosition]:
    recognizer = WeChatFriendListRecognizer(
        monitor_index=monitor_index,
        debug=debug,
        row_height=row_height,
        title_keyword=title_keyword,
        keep_all_rows=keep_all_rows,
    )
    recognizer.refresh()
    return recognizer.results


def main():
    parser = argparse.ArgumentParser(description="识别副屏微信好友/会话列表")
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
        "--row-height",
        type=int,
        default=72,
        help="微信会话行高度，默认 72",
    )
    parser.add_argument(
        "--title-keyword",
        default=None,
        help="可选：窗口标题关键词，比如 群名/文件传输助手/微信",
    )
    parser.add_argument(
        "--score-threshold",
        type=float,
        default=0.20,
        help="OCR 置信度阈值，默认 0.20。低于这个值 name 置空，但 raw_name 会保留。",
    )
    parser.add_argument(
        "--drop-invalid",
        action="store_true",
        help="开启后会丢掉低置信/无效名字的行；默认不丢，保留位置。",
    )

    args = parser.parse_args()

    print("3 秒后开始识别。微信不用 focus，但必须在指定屏幕上可见，不能被完全遮挡。")
    time.sleep(3)

    recognizer = WeChatFriendListRecognizer(
        monitor_index=args.monitor,
        debug=args.debug,
        row_height=args.row_height,
        title_keyword=args.title_keyword,
        score_threshold=args.score_threshold,
        keep_all_rows=not args.drop_invalid,
    )

    recognizer.refresh()

    # 这里演示 results 属性怎么 get。
    print()
    print("通过 recognizer.results 获取到的结果数量：", len(recognizer.results))


if __name__ == "__main__":
    main()
