#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
taskbar_icon_match_clicker.py

通用任务栏图标识别点击工具。

功能：
    1. 截取指定屏幕底部任务栏区域；
    2. 读取 icon 文件夹里的模板图片，比如 icon/a.png；
    3. 用 OpenCV 模板匹配在底部截图中找这个图标；
    4. 找到后点击图标中心。

适合：
    你想用一个通用方法识别任务栏里的任意图标。
    例如：
        icon/a.png 是你提前截好的微信图标、Edge 图标、文件夹图标等。

目录结构建议：
    D:/sync/pythonCode/opencvTest/
        taskbar_icon_match_clicker.py
        icon/
            a.png
            wechat.png
            edge.png

依赖：
    pip install opencv-python numpy mss

用法：
    python taskbar_icon_match_clicker.py --icon a.png
    python taskbar_icon_match_clicker.py --icon wechat.png --monitor 1 --debug
    python taskbar_icon_match_clicker.py --icon a.png --no-click --debug

monitor 说明：
    0 = 所有屏幕
    1 = 主屏
    2 = 副屏
"""

import argparse
import ctypes
import os
import platform
import time
from dataclasses import dataclass
from typing import Optional, Tuple, List

import cv2
import numpy as np
from mss import MSS


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DEBUG_DIR = os.path.join(SCRIPT_DIR, "debug_output")


@dataclass
class IconMatchResult:
    found: bool
    icon_path: str
    score: float

    # 截图底部区域内坐标
    x: int
    y: int
    w: int
    h: int

    # 屏幕绝对坐标
    click_x: int
    click_y: int

    # 模板缩放比例
    scale: float

    # 底部截图区域的屏幕偏移
    region_left: int
    region_top: int

    @property
    def box(self) -> Tuple[int, int, int, int]:
        return self.x, self.y, self.w, self.h

    @property
    def center(self) -> Tuple[int, int]:
        return self.click_x, self.click_y


class TaskbarIconMatchClicker:
    """
    通用底部任务栏图标模板匹配器。

    基本流程：
        bottom screenshot + template image -> matchTemplate -> best match -> click center

    说明：
        - 模板图建议尽量只包含图标本体，边缘不要留太多空白；
        - 如果模板是 png 且带透明通道，会自动用 alpha 当 mask；
        - 支持多尺度匹配，适配图标大小和截图大小略有差异的情况。
    """

    def __init__(
        self,
        icon_name: str,
        icon_dir: str = "icon",
        monitor_index: int = 1,
        bottom_height: int = 90,
        threshold: float = 0.72,
        debug: bool = False,
        scale_min: float = 0.70,
        scale_max: float = 1.35,
        scale_step: float = 0.05,
    ):
        self.icon_name = icon_name
        self.icon_dir = icon_dir
        self.monitor_index = monitor_index
        self.bottom_height = bottom_height
        self.threshold = threshold
        self.debug = debug

        self.scale_min = scale_min
        self.scale_max = scale_max
        self.scale_step = scale_step

        self.result: Optional[IconMatchResult] = None
        self.bottom_image: Optional[np.ndarray] = None
        self.bottom_region: Optional[dict] = None

    # -----------------------------
    # 基础工具
    # -----------------------------
    @staticmethod
    def enable_dpi_awareness():
        """
        Windows 高分屏下，尽量避免截图坐标和鼠标坐标不一致。
        """
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
        """
        保存调试图，支持中文路径。
        """
        TaskbarIconMatchClicker.ensure_debug_dir()
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
    def read_image_keep_alpha(path: str) -> np.ndarray:
        """
        支持中文路径读取图片，保留 alpha。
        """
        if not os.path.exists(path):
            raise FileNotFoundError(f"模板图片不存在: {path}")

        data = np.fromfile(path, dtype=np.uint8)
        img = cv2.imdecode(data, cv2.IMREAD_UNCHANGED)

        if img is None:
            raise RuntimeError(f"无法读取模板图片: {path}")

        return img

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

    def resolve_icon_path(self) -> str:
        """
        支持两种传法：
            --icon a.png
                => SCRIPT_DIR/icon/a.png

            --icon D:/xxx/a.png
                => 直接用绝对路径
        """
        icon_name = self.icon_name

        if os.path.isabs(icon_name):
            return icon_name

        # 先尝试当前脚本同级 icon 文件夹
        path1 = os.path.join(SCRIPT_DIR, self.icon_dir, icon_name)
        if os.path.exists(path1):
            return path1

        # 再尝试当前工作目录 icon 文件夹
        path2 = os.path.join(os.getcwd(), self.icon_dir, icon_name)
        if os.path.exists(path2):
            return path2

        # 最后尝试直接相对路径
        path3 = os.path.join(os.getcwd(), icon_name)
        if os.path.exists(path3):
            return path3

        # 返回最推荐的位置，方便错误提示
        return path1

    # -----------------------------
    # 截图
    # -----------------------------
    def screenshot_bottom(self) -> Tuple[np.ndarray, dict]:
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
            self.save_image("debug_icon_match_bottom.png", img)

        return img, region

    # -----------------------------
    # 模板处理
    # -----------------------------
    @staticmethod
    def prepare_template(template_raw: np.ndarray) -> Tuple[np.ndarray, Optional[np.ndarray]]:
        """
        返回：
            template_bgr
            mask

        如果 png 有 alpha，就用 alpha 作为 mask。
        """
        if template_raw.ndim == 2:
            template_bgr = cv2.cvtColor(template_raw, cv2.COLOR_GRAY2BGR)
            return template_bgr, None

        if template_raw.shape[2] == 4:
            bgr = template_raw[:, :, :3].copy()
            alpha = template_raw[:, :, 3]
            mask = cv2.threshold(alpha, 10, 255, cv2.THRESH_BINARY)[1]
            return bgr, mask

        if template_raw.shape[2] == 3:
            return template_raw, None

        raise RuntimeError(f"不支持的模板图片通道数: {template_raw.shape}")

    @staticmethod
    def resize_template(
        template_bgr: np.ndarray,
        mask: Optional[np.ndarray],
        scale: float,
    ) -> Tuple[np.ndarray, Optional[np.ndarray]]:
        h, w = template_bgr.shape[:2]
        new_w = max(1, int(round(w * scale)))
        new_h = max(1, int(round(h * scale)))

        resized = cv2.resize(
            template_bgr,
            (new_w, new_h),
            interpolation=cv2.INTER_AREA if scale < 1.0 else cv2.INTER_CUBIC,
        )

        resized_mask = None
        if mask is not None:
            resized_mask = cv2.resize(
                mask,
                (new_w, new_h),
                interpolation=cv2.INTER_NEAREST,
            )

        return resized, resized_mask

    def build_scale_list(self) -> List[float]:
        scales = []
        s = float(self.scale_min)

        while s <= self.scale_max + 1e-9:
            scales.append(round(s, 3))
            s += float(self.scale_step)

        # 确保 1.0 一定会尝试
        if 1.0 not in scales:
            scales.append(1.0)

        return sorted(set(scales))

    # -----------------------------
    # 模板匹配
    # -----------------------------
    @staticmethod
    def run_match(
        screenshot_bgr: np.ndarray,
        template_bgr: np.ndarray,
        mask: Optional[np.ndarray],
    ) -> Tuple[float, Tuple[int, int]]:
        """
        返回：
            best_score
            best_location: (x, y)

        用 TM_CCORR_NORMED：
            - 分数越高越像；
            - 支持 mask，适合透明 PNG。
        """
        if mask is not None:
            result = cv2.matchTemplate(
                screenshot_bgr,
                template_bgr,
                cv2.TM_CCORR_NORMED,
                mask=mask,
            )
        else:
            result = cv2.matchTemplate(
                screenshot_bgr,
                template_bgr,
                cv2.TM_CCOEFF_NORMED,
            )

        # 有些 OpenCV 版本在 mask 匹配时可能产生 nan/inf，这里清理一下
        result = np.nan_to_num(result, nan=-1.0, posinf=-1.0, neginf=-1.0)

        _, max_val, _, max_loc = cv2.minMaxLoc(result)

        return float(max_val), max_loc

    def match_icon(self, screenshot_bgr: np.ndarray, region: dict) -> Optional[IconMatchResult]:
        icon_path = self.resolve_icon_path()
        template_raw = self.read_image_keep_alpha(icon_path)
        template_bgr, mask = self.prepare_template(template_raw)

        if self.debug:
            self.save_image("debug_icon_template.png", template_bgr)
            if mask is not None:
                self.save_image("debug_icon_template_mask.png", mask)

        sh, sw = screenshot_bgr.shape[:2]

        best = None

        for scale in self.build_scale_list():
            resized, resized_mask = self.resize_template(template_bgr, mask, scale)
            th, tw = resized.shape[:2]

            if tw > sw or th > sh:
                continue

            if tw < 5 or th < 5:
                continue

            score, loc = self.run_match(
                screenshot_bgr=screenshot_bgr,
                template_bgr=resized,
                mask=resized_mask,
            )

            if self.debug:
                print(
                    f"scale={scale:.3f}, template=({tw}x{th}), "
                    f"score={score:.4f}, loc={loc}"
                )

            if best is None or score > best["score"]:
                best = {
                    "score": score,
                    "x": int(loc[0]),
                    "y": int(loc[1]),
                    "w": int(tw),
                    "h": int(th),
                    "scale": float(scale),
                    "icon_path": icon_path,
                }

        if best is None:
            return None

        if best["score"] < self.threshold:
            print(
                f"找到最高匹配，但分数不够: score={best['score']:.4f}, "
                f"threshold={self.threshold:.4f}"
            )

            if self.debug:
                self.save_match_debug_image(screenshot_bgr, best, passed=False)

            return None

        click_x = int(region["left"] + best["x"] + best["w"] // 2)
        click_y = int(region["top"] + best["y"] + best["h"] // 2)

        result = IconMatchResult(
            found=True,
            icon_path=str(best["icon_path"]),
            score=float(best["score"]),
            x=int(best["x"]),
            y=int(best["y"]),
            w=int(best["w"]),
            h=int(best["h"]),
            click_x=click_x,
            click_y=click_y,
            scale=float(best["scale"]),
            region_left=int(region["left"]),
            region_top=int(region["top"]),
        )

        if self.debug:
            self.save_match_debug_image(screenshot_bgr, best, passed=True)

        return result

    def save_match_debug_image(self, screenshot_bgr: np.ndarray, best: dict, passed: bool):
        dbg = screenshot_bgr.copy()

        x = best["x"]
        y = best["y"]
        w = best["w"]
        h = best["h"]
        score = best["score"]
        scale = best["scale"]

        color = (0, 255, 0) if passed else (0, 0, 255)

        cv2.rectangle(dbg, (x, y), (x + w, y + h), color, 2)
        cv2.circle(dbg, (x + w // 2, y + h // 2), 4, color, -1)
        cv2.putText(
            dbg,
            f"score={score:.3f}, scale={scale:.2f}",
            (x, max(18, y - 8)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            color,
            2,
        )

        self.save_image("debug_icon_match_result.png", dbg)

    # -----------------------------
    # 对外方法
    # -----------------------------
    def refresh(self) -> Optional[IconMatchResult]:
        self.enable_dpi_awareness()

        screenshot, region = self.screenshot_bottom()
        self.result = self.match_icon(screenshot, region)

        if self.result is None:
            print("没有匹配到指定图标。可以加 --debug 查看调试图。")
            return None

        print(
            f"匹配到图标: icon={self.result.icon_path}, "
            f"score={self.result.score:.4f}, "
            f"box=({self.result.x}, {self.result.y}, {self.result.w}, {self.result.h}), "
            f"click=({self.result.click_x}, {self.result.click_y}), "
            f"scale={self.result.scale:.2f}"
        )

        return self.result

    def click_icon(self) -> bool:
        if self.result is None:
            return False

        self.click_screen_position(self.result.click_x, self.result.click_y)
        print("已点击匹配到的图标。")
        return True

    def refresh_and_click(self) -> Optional[IconMatchResult]:
        result = self.refresh()

        if result is not None:
            self.click_icon()

        return result


def click_icon_from_taskbar(
    icon_name: str,
    icon_dir: str = "icon",
    monitor_index: int = 1,
    bottom_height: int = 90,
    threshold: float = 0.72,
    debug: bool = False,
    scale_min: float = 0.70,
    scale_max: float = 1.35,
    scale_step: float = 0.05,
) -> bool:
    """
    函数式调用入口。
    """
    clicker = TaskbarIconMatchClicker(
        icon_name=icon_name,
        icon_dir=icon_dir,
        monitor_index=monitor_index,
        bottom_height=bottom_height,
        threshold=threshold,
        debug=debug,
        scale_min=scale_min,
        scale_max=scale_max,
        scale_step=scale_step,
    )

    result = clicker.refresh_and_click()
    return result is not None


def main():
    parser = argparse.ArgumentParser(description="通用任务栏底部图标模板匹配并点击")
    parser.add_argument(
        "--icon",
        "-i",
        default="ytsaver.png",
        help="模板图片文件名。默认 a.png。会优先从 icon 文件夹读取。",
    )
    parser.add_argument(
        "--icon-dir",
        default="icon",
        help="模板图片文件夹，默认 icon",
    )
    parser.add_argument(
        "--monitor",
        type=int,
        default=1,
        help="截图屏幕：0=所有屏幕，1=主屏，2=副屏。默认 1",
    )
    parser.add_argument(
        "--bottom-height",
        type=int,
        default=90,
        help="截取屏幕底部高度，默认 90 像素",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.72,
        help="匹配阈值，默认 0.72。匹配不到可降低到 0.65",
    )
    parser.add_argument(
        "--scale-min",
        type=float,
        default=0.70,
        help="模板最小缩放比例，默认 0.70",
    )
    parser.add_argument(
        "--scale-max",
        type=float,
        default=1.35,
        help="模板最大缩放比例，默认 1.35",
    )
    parser.add_argument(
        "--scale-step",
        type=float,
        default=0.05,
        help="模板缩放步长，默认 0.05",
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

    print(f"{args.delay} 秒后开始识别底部任务栏图标。")
    time.sleep(args.delay)

    clicker = TaskbarIconMatchClicker(
        icon_name=args.icon,
        icon_dir=args.icon_dir,
        monitor_index=args.monitor,
        bottom_height=args.bottom_height,
        threshold=args.threshold,
        debug=args.debug,
        scale_min=args.scale_min,
        scale_max=args.scale_max,
        scale_step=args.scale_step,
    )

    result = clicker.refresh()

    if result is None:
        return

    if not args.no_click:
        clicker.click_icon()


if __name__ == "__main__":
    main()
