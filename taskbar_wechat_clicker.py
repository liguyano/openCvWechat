#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
taskbar_wechat_clicker.py

功能：
    从屏幕最底部截图，识别 Windows 任务栏里的微信图标，然后点击它。

适用场景：
    你想先从任务栏打开/激活微信，再继续执行 main.py 里的搜索好友、输入、发送流程。

依赖：
    pip install opencv-python numpy mss

用法：
    python taskbar_wechat_clicker.py
    python taskbar_wechat_clicker.py --monitor 1 --debug
    python taskbar_wechat_clicker.py --monitor 0 --bottom-height 80 --debug

monitor 说明：
    0 = 所有屏幕
    1 = 主屏
    2 = 副屏

默认 monitor=1，因为 Windows 任务栏一般在主屏底部。
"""

import argparse
import ctypes
import os
import platform
import time
from dataclasses import dataclass
from typing import List, Optional, Tuple

import cv2
import numpy as np
from mss import MSS


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DEBUG_DIR = os.path.join(SCRIPT_DIR, "debug_output")


@dataclass
class TaskbarIconResult:
    found: bool
    x: int
    y: int
    w: int
    h: int
    click_x: int
    click_y: int
    score: float
    monitor_left: int
    monitor_top: int

    @property
    def box(self) -> Tuple[int, int, int, int]:
        return self.x, self.y, self.w, self.h

    @property
    def center(self) -> Tuple[int, int]:
        return self.click_x, self.click_y


class TaskbarWeChatClicker:
    """
    从任务栏底部截图中识别微信图标。

    识别逻辑：
        1. 截取指定屏幕最底部 bottom_height 像素；
        2. 用 HSV 找绿色区域；
        3. 过滤出接近正方形的小图标；
        4. 检查绿色图标内部是否有白色聊天气泡轮廓；
        5. 选分数最高的候选并点击。
    """

    def __init__(
        self,
        monitor_index: int = 1,
        bottom_height: int = 80,
        debug: bool = False,
    ):
        self.monitor_index = monitor_index
        self.bottom_height = bottom_height
        self.debug = debug

        self.result: Optional[TaskbarIconResult] = None
        self.bottom_image: Optional[np.ndarray] = None
        self.bottom_region: Optional[dict] = None

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
        TaskbarWeChatClicker.ensure_debug_dir()
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
    def click_screen_position(x: int, y: int):
        """
        点击屏幕绝对坐标。
        Windows 下直接用 API，避免副屏/缩放时 pyautogui 坐标不准。
        """
        if platform.system().lower() == "windows":
            user32 = ctypes.windll.user32
            user32.SetCursorPos(int(x), int(y))
            time.sleep(0.05)
            user32.mouse_event(0x0002, 0, 0, 0, 0)  # left down
            time.sleep(0.05)
            user32.mouse_event(0x0004, 0, 0, 0, 0)  # left up
        else:
            import pyautogui
            pyautogui.click(int(x), int(y))

    @staticmethod
    def list_monitors():
        with MSS() as sct:
            print("当前屏幕列表：")
            for i, m in enumerate(sct.monitors):
                print(
                    f"monitor {i}: left={m['left']}, top={m['top']}, "
                    f"width={m['width']}, height={m['height']}"
                )

            return [dict(m) for m in sct.monitors]

    def screenshot_taskbar_bottom(self) -> Tuple[np.ndarray, dict]:
        """
        截取指定屏幕最底部区域。
        """
        with MSS() as sct:
            print("当前屏幕列表：")
            for i, m in enumerate(sct.monitors):
                print(
                    f"monitor {i}: left={m['left']}, top={m['top']}, "
                    f"width={m['width']}, height={m['height']}"
                )

            if self.monitor_index >= len(sct.monitors):
                raise ValueError(
                    f"monitor_index={self.monitor_index} 不存在，最多只能选到 {len(sct.monitors) - 1}"
                )

            monitor = dict(sct.monitors[self.monitor_index])

            height = min(int(self.bottom_height), int(monitor["height"]))
            region = {
                "left": int(monitor["left"]),
                "top": int(monitor["top"] + monitor["height"] - height),
                "width": int(monitor["width"]),
                "height": int(height),
            }

            raw = np.array(sct.grab(region))

        img = cv2.cvtColor(raw, cv2.COLOR_BGRA2BGR)

        self.bottom_image = img
        self.bottom_region = region

        if self.debug:
            self.save_image("debug_taskbar_bottom.png", img)

        return img, region

    # -----------------------------
    # 微信图标识别
    # -----------------------------
    @staticmethod
    def _merge_nearby_boxes(boxes: List[Tuple[int, int, int, int]]) -> List[Tuple[int, int, int, int]]:
        """
        合并距离很近的绿色碎片。
        有些图标会被分成多个绿色轮廓。
        """
        if not boxes:
            return []

        rects = []
        for x, y, w, h in boxes:
            rects.append([x, y, x + w, y + h])

        changed = True
        while changed:
            changed = False
            merged = []
            used = [False] * len(rects)

            for i, a in enumerate(rects):
                if used[i]:
                    continue

                ax1, ay1, ax2, ay2 = a
                used[i] = True

                for j in range(i + 1, len(rects)):
                    if used[j]:
                        continue

                    bx1, by1, bx2, by2 = rects[j]

                    # 两个绿色碎片如果很近，就合并
                    gap_x = max(0, max(bx1 - ax2, ax1 - bx2))
                    gap_y = max(0, max(by1 - ay2, ay1 - by2))

                    if gap_x <= 8 and gap_y <= 8:
                        ax1 = min(ax1, bx1)
                        ay1 = min(ay1, by1)
                        ax2 = max(ax2, bx2)
                        ay2 = max(ay2, by2)
                        used[j] = True
                        changed = True

                merged.append([ax1, ay1, ax2, ay2])

            rects = merged

        return [(x1, y1, x2 - x1, y2 - y1) for x1, y1, x2, y2 in rects]

    @staticmethod
    def _score_wechat_icon_candidate(img: np.ndarray, box: Tuple[int, int, int, int]) -> float:
        """
        给一个绿色候选图标打分。
        微信图标特征：
            - 绿色区域接近正方形；
            - 内部白色区域明显；
            - 白色轮廓位置在绿色方块内；
            - 大小类似任务栏图标。
        """
        h, w = img.shape[:2]
        x, y, bw, bh = box

        pad = 5
        x1 = max(0, x - pad)
        y1 = max(0, y - pad)
        x2 = min(w, x + bw + pad)
        y2 = min(h, y + bh + pad)

        crop = img[y1:y2, x1:x2]
        if crop.size == 0:
            return -999.0

        hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)

        # 微信图标主体绿色
        green_mask = cv2.inRange(
            hsv,
            np.array([35, 50, 60]),
            np.array([95, 255, 255]),
        )

        # 微信图标内部白色气泡
        white_mask = cv2.inRange(
            hsv,
            np.array([0, 0, 175]),
            np.array([180, 95, 255]),
        )

        green_ratio = float(np.mean(green_mask > 0))
        white_ratio = float(np.mean(white_mask > 0))

        aspect = bw / max(bh, 1)
        size_score = 0.0

        # 任务栏图标里实际绿色主体通常 18~36 像素左右
        if 16 <= bw <= 42 and 16 <= bh <= 42:
            size_score += 2.0
        elif 10 <= bw <= 55 and 10 <= bh <= 55:
            size_score += 0.8
        else:
            size_score -= 2.0

        square_score = max(0.0, 1.0 - abs(aspect - 1.0)) * 2.0

        # 找白色聊天气泡轮廓
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
        white_clean = cv2.morphologyEx(white_mask, cv2.MORPH_OPEN, kernel, iterations=1)

        contours, _ = cv2.findContours(
            white_clean,
            cv2.RETR_EXTERNAL,
            cv2.CHAIN_APPROX_SIMPLE,
        )

        white_blob_score = 0.0
        white_blob_count = 0

        for cnt in contours:
            area = cv2.contourArea(cnt)
            px, py, pw, ph = cv2.boundingRect(cnt)

            if area < 4:
                continue

            if pw > crop.shape[1] * 0.95 or ph > crop.shape[0] * 0.95:
                continue

            white_blob_count += 1
            white_blob_score += min(area / 35.0, 2.0)

        # 微信图标可能两个气泡连在一起，所以 count 不一定是 2。
        if white_blob_count >= 1:
            white_blob_score += 2.0

        # 绿色比例和白色比例约束。
        # Edge/PyCharm 等图标也可能有绿色，但通常白色气泡比例不对。
        ratio_score = 0.0

        if green_ratio >= 0.30:
            ratio_score += 2.0
        elif green_ratio >= 0.18:
            ratio_score += 0.8
        else:
            ratio_score -= 1.0

        if 0.06 <= white_ratio <= 0.30:
            ratio_score += 2.0
        elif 0.03 <= white_ratio <= 0.40:
            ratio_score += 0.6
        else:
            ratio_score -= 1.0

        # 任务栏底部的蓝色下划线、其他小碎片不应该被选中
        if bh < 12 or bw < 12:
            ratio_score -= 3.0

        score = (
            size_score
            + square_score
            + ratio_score
            + white_blob_score
            + green_ratio * 3.0
            + white_ratio * 4.0
        )

        return float(score)

    def detect_wechat_icon(self, img: np.ndarray, region: dict) -> Optional[TaskbarIconResult]:
        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)

        # 微信绿色。这里范围稍微放宽，适配不同显示器颜色。
        green_mask = cv2.inRange(
            hsv,
            np.array([35, 45, 55]),
            np.array([95, 255, 255]),
        )

        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
        green_mask = cv2.morphologyEx(green_mask, cv2.MORPH_CLOSE, kernel, iterations=2)

        if self.debug:
            self.save_image("debug_taskbar_green_mask.png", green_mask)

        contours, _ = cv2.findContours(
            green_mask,
            cv2.RETR_EXTERNAL,
            cv2.CHAIN_APPROX_SIMPLE,
        )

        raw_boxes = []

        for cnt in contours:
            x, y, bw, bh = cv2.boundingRect(cnt)
            area = bw * bh

            if area < 40:
                continue

            if bw > 90 or bh > 70:
                continue

            raw_boxes.append((x, y, bw, bh))

        merged_boxes = self._merge_nearby_boxes(raw_boxes)

        candidates = []

        for box in merged_boxes:
            x, y, bw, bh = box

            # 去掉任务栏下划线这种超扁长条
            if bh < 10 or bw < 10:
                continue

            if bw > 80 or bh > 60:
                continue

            score = self._score_wechat_icon_candidate(img, box)

            if self.debug:
                print(f"候选绿色图标: x={x}, y={y}, w={bw}, h={bh}, score={score:.2f}")

            if score < 5.0:
                continue

            candidates.append((score, x, y, bw, bh))

        if self.debug:
            dbg = img.copy()
            for score, x, y, bw, bh in candidates:
                cv2.rectangle(dbg, (x, y), (x + bw, y + bh), (0, 255, 0), 2)
                cv2.putText(
                    dbg,
                    f"{score:.1f}",
                    (x, max(12, y - 4)),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.45,
                    (0, 0, 255),
                    1,
                )
            self.save_image("debug_taskbar_wechat_candidates.png", dbg)

        if not candidates:
            return None

        # 分数最高就是微信图标
        candidates.sort(key=lambda item: item[0], reverse=True)
        score, x, y, bw, bh = candidates[0]

        click_x = int(region["left"] + x + bw // 2)
        click_y = int(region["top"] + y + bh // 2)

        result = TaskbarIconResult(
            found=True,
            x=int(x),
            y=int(y),
            w=int(bw),
            h=int(bh),
            click_x=click_x,
            click_y=click_y,
            score=float(score),
            monitor_left=int(region["left"]),
            monitor_top=int(region["top"]),
        )

        if self.debug:
            dbg = img.copy()
            cv2.rectangle(dbg, (x, y), (x + bw, y + bh), (0, 255, 0), 2)
            cv2.circle(dbg, (x + bw // 2, y + bh // 2), 4, (0, 0, 255), -1)
            cv2.putText(
                dbg,
                "WeChat taskbar icon",
                (x, max(18, y - 8)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                (0, 255, 0),
                2,
            )
            self.save_image("debug_taskbar_wechat_result.png", dbg)

        return result

    # -----------------------------
    # 对外方法
    # -----------------------------
    def refresh(self) -> Optional[TaskbarIconResult]:
        self.enable_dpi_awareness()

        img, region = self.screenshot_taskbar_bottom()
        self.result = self.detect_wechat_icon(img, region)

        if self.result is None:
            print("没有识别到任务栏微信图标。可以加 --debug 查看 debug_output 里的调试图。")
        else:
            print(
                f"识别到任务栏微信图标: "
                f"box=({self.result.x}, {self.result.y}, {self.result.w}, {self.result.h}), "
                f"click=({self.result.click_x}, {self.result.click_y}), "
                f"score={self.result.score:.2f}"
            )

        return self.result

    def click_wechat_icon(self) -> bool:
        if self.result is None:
            return False

        self.click_screen_position(self.result.click_x, self.result.click_y)
        print("已点击任务栏微信图标。")
        return True

    def refresh_and_click(self) -> Optional[TaskbarIconResult]:
        result = self.refresh()
        if result is not None:
            self.click_wechat_icon()
        return result


def click_wechat_from_taskbar(
    monitor_index: int = 1,
    bottom_height: int = 80,
    debug: bool = False,
) -> bool:
    """
    函数式调用入口。
    """
    clicker = TaskbarWeChatClicker(
        monitor_index=monitor_index,
        bottom_height=bottom_height,
        debug=debug,
    )

    result = clicker.refresh_and_click()
    return result is not None


def main():
    parser = argparse.ArgumentParser(description="从屏幕底部任务栏识别微信图标并点击")
    parser.add_argument(
        "--monitor",
        type=int,
        default=1,
        help="截图屏幕：0=所有屏幕，1=主屏，2=副屏。默认 1",
    )
    parser.add_argument(
        "--bottom-height",
        type=int,
        default=80,
        help="截取屏幕底部高度，默认 80 像素",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="保存调试图片",
    )
    parser.add_argument(
        "--no-click",
        action="store_true",
        help="只识别，不点击",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=1.0,
        help="开始前等待秒数，默认 1 秒",
    )

    args = parser.parse_args()

    print(f"{args.delay} 秒后开始识别任务栏微信图标。")
    time.sleep(args.delay)

    clicker = TaskbarWeChatClicker(
        monitor_index=args.monitor,
        bottom_height=args.bottom_height,
        debug=args.debug,
    )

    result = clicker.refresh()

    if result is None:
        return

    if not args.no_click:
        clicker.click_wechat_icon()


if __name__ == "__main__":
    main()
