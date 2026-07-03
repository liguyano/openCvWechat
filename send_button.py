#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import ctypes
import os
import platform
import time

import cv2
import numpy as np
import pyautogui
from mss import MSS


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DEBUG_DIR = os.path.join(SCRIPT_DIR, "debug_output")


def enable_dpi_awareness():
    """
    Windows 高分屏下，避免截图坐标和鼠标坐标对不上。
    """
    if platform.system().lower() == "windows":
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            try:
                ctypes.windll.user32.SetProcessDPIAware()
            except Exception:
                pass


def ensure_debug_dir():
    os.makedirs(DEBUG_DIR, exist_ok=True)


def save_image(filename, img):
    ensure_debug_dir()
    path = os.path.join(DEBUG_DIR, filename)

    ext = os.path.splitext(path)[1]
    ok, data = cv2.imencode(ext, img)

    if ok:
        data.tofile(path)
        print(f"已保存: {path}")
    else:
        print(f"保存失败: {path}")

    return path


def screenshot_monitor(monitor_index=2, debug=False):
    """
    截取指定屏幕。

    monitor_index:
        0 = 所有屏幕
        1 = 主屏
        2 = 副屏
    """
    with MSS() as sct:
        print("当前屏幕列表：")
        for i, m in enumerate(sct.monitors):
            print(
                f"monitor {i}: "
                f"left={m['left']}, top={m['top']}, "
                f"width={m['width']}, height={m['height']}"
            )

        if monitor_index >= len(sct.monitors):
            raise ValueError(
                f"monitor_index={monitor_index} 不存在，最多只能选到 {len(sct.monitors) - 1}"
            )

        region = sct.monitors[monitor_index]
        raw = np.array(sct.grab(region))

    img = cv2.cvtColor(raw, cv2.COLOR_BGRA2BGR)

    if debug:
        save_image("debug_send_monitor_screenshot.png", img)

    return img, region


def has_voice_icon_left_of_button(img, button_box, debug=False):
    """
    辅助识别：
    判断绿色发送按钮左边附近，是否存在那个圆形语音/喇叭图标。

    button_box: (x, y, bw, bh)
    坐标是截图内部坐标，不是全局屏幕坐标。
    """
    h, w = img.shape[:2]
    x, y, bw, bh = button_box

    btn_cy = y + bh // 2

    # 只看发送按钮左边一小块区域
    # 你的截图里语音图标大概在发送按钮左侧 50~120 像素处
    roi_x1 = max(0, x - 180)
    roi_x2 = max(0, x - 8)
    roi_y1 = max(0, btn_cy - 45)
    roi_y2 = min(h, btn_cy + 45)

    if roi_x2 <= roi_x1 or roi_y2 <= roi_y1:
        return False

    roi = img[roi_y1:roi_y2, roi_x1:roi_x2]

    if debug:
        save_image("debug_voice_icon_roi.png", roi)

    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    blur = cv2.GaussianBlur(gray, (3, 3), 0)

    # 语音图标是灰黑色线条，用边缘检测
    edges = cv2.Canny(blur, 40, 120)

    if debug:
        save_image("debug_voice_icon_edges.png", edges)

    # 先用霍夫圆找圆形外框
    circles = cv2.HoughCircles(
        blur,
        cv2.HOUGH_GRADIENT,
        dp=1.2,
        minDist=15,
        param1=80,
        param2=13,
        minRadius=6,
        maxRadius=18,
    )

    debug_img = roi.copy()
    found_circle = False

    if circles is not None:
        circles = np.round(circles[0]).astype(int)

        for cx, cy, r in circles:
            global_cx = roi_x1 + cx
            global_cy = roi_y1 + cy

            # 要求圆心和发送按钮中心高度接近
            if abs(global_cy - btn_cy) > 25:
                continue

            # 要求圆在按钮左边，不能太贴近按钮
            if global_cx >= x - 5:
                continue

            found_circle = True

            if debug:
                cv2.circle(debug_img, (cx, cy), r, (0, 255, 0), 2)
                cv2.circle(debug_img, (cx, cy), 2, (0, 0, 255), 2)

            break

    if debug:
        save_image("debug_voice_icon_circle_result.png", debug_img)

    if found_circle:
        return True

    # 兜底方案：
    # 有些情况下霍夫圆不稳定，就检查这个区域里是否有一个“小的灰黑色图标轮廓”
    _, dark = cv2.threshold(gray, 150, 255, cv2.THRESH_BINARY_INV)

    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    dark = cv2.morphologyEx(dark, cv2.MORPH_OPEN, kernel, iterations=1)

    if debug:
        save_image("debug_voice_icon_dark_mask.png", dark)

    contours, _ = cv2.findContours(
        dark,
        cv2.RETR_EXTERNAL,
        cv2.CHAIN_APPROX_SIMPLE,
    )

    possible_icon_parts = 0

    for cnt in contours:
        px, py, pw, ph = cv2.boundingRect(cnt)
        area = pw * ph

        global_px = roi_x1 + px
        global_py = roi_y1 + py
        global_cy = global_py + ph // 2

        # 图标碎片一般不会太大，也不会太小
        if area < 8 or area > 500:
            continue

        if pw > 35 or ph > 35:
            continue

        # 高度要和按钮中心接近
        if abs(global_cy - btn_cy) > 30:
            continue

        # 必须在按钮左边
        if global_px >= x:
            continue

        possible_icon_parts += 1

    print(f"语音图标灰黑轮廓数量: {possible_icon_parts}")

    # 圆圈 + 内部喇叭线条，通常会有多个小轮廓
    return possible_icon_parts >= 2


def detect_green_send_button(img, debug=False):
    """
    在截图里识别绿色发送按钮。

    加强版：
    1. 先找绿色矩形；
    2. 再检查它左边是否有语音/喇叭圆形图标；
    3. 只有满足这个辅助条件，才认为是发送按钮。
    """
    h, w = img.shape[:2]

    # 发送按钮一般在聊天窗口下半部分
    roi_top = int(h * 0.45)
    roi_left = 0
    roi = img[roi_top:h, roi_left:w]

    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)

    # 绿色按钮范围
    lower_green = np.array([35, 60, 80])
    upper_green = np.array([95, 255, 255])

    mask = cv2.inRange(hsv, lower_green, upper_green)

    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)
    mask = cv2.dilate(mask, kernel, iterations=1)

    if debug:
        save_image("debug_send_button_mask.png", mask)

    contours, _ = cv2.findContours(
        mask,
        cv2.RETR_EXTERNAL,
        cv2.CHAIN_APPROX_SIMPLE,
    )

    candidates = []

    debug_candidates = img.copy()

    for cnt in contours:
        x, y, bw, bh = cv2.boundingRect(cnt)

        real_x = x + roi_left
        real_y = y + roi_top

        area = bw * bh
        aspect = bw / max(bh, 1)

        # 发送按钮通常是一个小横向矩形
        if bw < 35 or bw > 160:
            continue

        if bh < 18 or bh > 70:
            continue

        if aspect < 1.2 or aspect > 6.0:
            continue

        if area < 500:
            continue

        button_box = (real_x, real_y, bw, bh)

        # 核心新增：绿色按钮左边必须有语音图标
        has_voice_icon = has_voice_icon_left_of_button(
            img,
            button_box,
            debug=debug,
        )

        print(
            f"绿色候选: x={real_x}, y={real_y}, w={bw}, h={bh}, "
            f"has_voice_icon={has_voice_icon}"
        )

        if debug:
            color = (0, 255, 0) if has_voice_icon else (0, 0, 255)
            cv2.rectangle(
                debug_candidates,
                (real_x, real_y),
                (real_x + bw, real_y + bh),
                color,
                2,
            )

        if not has_voice_icon:
            continue

        # 发送按钮一般偏右下
        score = real_y * 3 + real_x * 1.2 + area

        candidates.append((score, real_x, real_y, bw, bh))

    if debug:
        save_image("debug_send_candidates_with_voice_check.png", debug_candidates)

    print(f"绿色发送按钮候选数量: {len(candidates)}")

    if not candidates:
        return None

    candidates.sort(reverse=True)
    _, x, y, bw, bh = candidates[0]

    return x, y, bw, bh


def click_send_button_from_monitor(monitor_index=2, debug=False):
    """
    从指定屏幕截图，识别绿色发送按钮并点击。

    默认 monitor_index=2，也就是副屏。
    """
    enable_dpi_awareness()
    pyautogui.FAILSAFE = True

    img, region = screenshot_monitor(
        monitor_index=monitor_index,
        debug=debug,
    )

    button = detect_green_send_button(img, debug=debug)

    if button is None:
        print("没有识别到带语音图标辅助确认的绿色发送按钮")
        if debug:
            save_image("debug_send_no_button.png", img)
        return False

    x, y, bw, bh = button

    print(f"识别到发送按钮: x={x}, y={y}, w={bw}, h={bh}")

    if debug:
        debug_img = img.copy()
        cv2.rectangle(debug_img, (x, y), (x + bw, y + bh), (0, 255, 0), 2)

        # 顺手画一下左侧语音图标搜索区域
        btn_cy = y + bh // 2
        roi_x1 = max(0, x - 180)
        roi_x2 = max(0, x - 8)
        roi_y1 = max(0, btn_cy - 45)
        roi_y2 = min(img.shape[0], btn_cy + 45)

        cv2.rectangle(debug_img, (roi_x1, roi_y1), (roi_x2, roi_y2), (255, 0, 0), 2)

        save_image("debug_send_button_result.png", debug_img)

    # 副屏截图坐标要加上副屏的 left / top 偏移
    screen_left = region["left"]
    screen_top = region["top"]

    click_x = screen_left + x + bw // 2
    click_y = screen_top + y + bh // 2

    print(f"点击发送按钮中心，全局坐标: x={click_x}, y={click_y}")

    time.sleep(0.2)
    pyautogui.click(click_x, click_y)

    return True


def click_send(debug=False):
    """
    默认从副屏 monitor 2 识别并点击发送按钮。
    """
    return click_send_button_from_monitor(
        monitor_index=2,
        debug=debug,
    )


if __name__ == "__main__":
    print("3 秒后开始，请确保副屏上的微信输入框里已经有文字，发送按钮是绿色的...")
    time.sleep(3)

    click_send(debug=True)