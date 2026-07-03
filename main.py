#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
mai.py

功能：
    1. 使用 wechat_search_box_recognizer_click.py 识别并点击微信左上角搜索框；
    2. 把固定好友关键词粘贴到搜索框；
    3. 不再识别搜索结果，直接点击搜索框下方第一个结果；
    4. 进入聊天后，识别聊天输入框；
    5. 粘贴消息；
    6. 调用 send_button.py 点击发送按钮。

依赖：
    pip install opencv-python numpy mss pyautogui pyperclip

同目录需要有：
    wechat_search_box_recognizer_click.py
    taskbar_wechat_clicker.py
    send_button.py
"""

import argparse
import ctypes
import os
import platform
import time

import cv2
import numpy as np
import pyautogui
import pyperclip
from mss import MSS

import send_button
from wechat_search_box_recognizer_click import WeChatSearchBoxRecognizer

try:
    from taskbar_wechat_clicker import click_wechat_from_taskbar
except Exception as e:
    click_wechat_from_taskbar = None
    TASKBAR_WECHAT_IMPORT_ERROR = e
else:
    TASKBAR_WECHAT_IMPORT_ERROR = None


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


enable_dpi_awareness()

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DEBUG_DIR = os.path.join(SCRIPT_DIR, "debug_output")


def ensure_debug_dir():
    os.makedirs(DEBUG_DIR, exist_ok=True)


def save_image(filename, img):
    """
    保存调试图片到 mai.py 同级目录的 debug_output 文件夹。
    支持中文路径。
    """
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


def screenshot_monitor(monitor_index=2):
    """
    直接截取指定显示器。

    monitor_index:
        0 = 所有屏幕
        1 = 主屏
        2 = 副屏
    """
    with MSS() as sct:
        print("当前屏幕列表：")
        for i, m in enumerate(sct.monitors):
            print(
                f"monitor {i}: left={m['left']}, top={m['top']}, "
                f"width={m['width']}, height={m['height']}"
            )

        if monitor_index >= len(sct.monitors):
            raise ValueError(
                f"monitor {monitor_index} 不存在，最多只能选到 {len(sct.monitors) - 1}"
            )

        region = sct.monitors[monitor_index]
        raw = np.array(sct.grab(region))

    img = cv2.cvtColor(raw, cv2.COLOR_BGRA2BGR)
    save_image("debug_monitor_screenshot.png", img)

    return img, region


def click_screen_position(x: int, y: int):
    """
    点击屏幕绝对坐标。
    优先用 Windows API，避免某些情况下 pyautogui 在副屏坐标上有偏差。
    """
    if platform.system().lower() == "windows":
        user32 = ctypes.windll.user32
        user32.SetCursorPos(int(x), int(y))
        time.sleep(0.05)

        # MOUSEEVENTF_LEFTDOWN = 0x0002
        # MOUSEEVENTF_LEFTUP = 0x0004
        user32.mouse_event(0x0002, 0, 0, 0, 0)
        time.sleep(0.05)
        user32.mouse_event(0x0004, 0, 0, 0, 0)
    else:
        pyautogui.click(int(x), int(y))


def hotkey_select_all():
    if platform.system().lower() == "darwin":
        pyautogui.hotkey("command", "a")
    else:
        pyautogui.hotkey("ctrl", "a")


def hotkey_paste():
    if platform.system().lower() == "darwin":
        pyautogui.hotkey("command", "v")
    else:
        pyautogui.hotkey("ctrl", "v")


def search_friend_and_click_first_result(
    friend_keyword: str = "ウィーエト",
    monitor_index: int = 2,
    debug_search: bool = False,
    title_keyword: str | None = None,
    result_offset_x: int = 0,
    result_offset_y: int = 78,
    wait_after_paste: float = 0.8,
    taskbar_monitor_index: int = 1,
    taskbar_bottom_height: int = 80,
    taskbar_debug: bool = False,
    wait_after_taskbar_click: float = 1.2,
):
    """
    使用微信左上角搜索框进入固定好友聊天。

    流程：
        1. 调用 wechat_search_box_recognizer_click.py 识别搜索框；
        2. 点击搜索框；
        3. Ctrl+A 清空旧搜索词；
        4. 粘贴 friend_keyword；
        5. 等搜索结果出现；
        6. 不再用 OpenCV 识别结果，直接点击搜索框下方固定偏移位置。

    默认：
        first_result_x = search_box_center_x
        first_result_y = search_box_center_y + 78

    如果点击偏上/偏下，可以调 --result-offset-y。
    """
    recognizer = WeChatSearchBoxRecognizer(
        monitor_index=monitor_index,
        debug=debug_search,
        title_keyword=title_keyword,
    )

    result = recognizer.refresh()

    if result is None:
        print("第一次没有识别到微信搜索框，尝试从任务栏点击微信图标后重试。")

        if click_wechat_from_taskbar is None:
            print("无法导入 taskbar_wechat_clicker.py，不能从任务栏点击微信。")
            print(f"导入错误: {TASKBAR_WECHAT_IMPORT_ERROR}")
            return False

        clicked = click_wechat_from_taskbar(
            monitor_index=taskbar_monitor_index,
            bottom_height=taskbar_bottom_height,
            debug=taskbar_debug,
        )

        if not clicked:
            print("没有识别到任务栏微信图标，无法打开/激活微信。")
            return False

        print(f"已从任务栏点击微信，等待 {wait_after_taskbar_click} 秒后重新识别搜索框。")
        time.sleep(wait_after_taskbar_click)

        recognizer = WeChatSearchBoxRecognizer(
            monitor_index=monitor_index,
            debug=debug_search,
            title_keyword=title_keyword,
        )
        result = recognizer.refresh()

        if result is None:
            print("从任务栏点击微信后，仍然没有识别到微信搜索框，停止搜索好友。")
            return False

    print()
    print("搜索框识别结果：")
    print(f"box=({result.x}, {result.y}, {result.w}, {result.h})")
    print(f"search_click=({result.click_x}, {result.click_y})")

    recognizer.click_search_box()
    time.sleep(0.2)

    hotkey_select_all()
    time.sleep(0.08)
    pyautogui.press("backspace")
    time.sleep(0.08)

    pyperclip.copy(friend_keyword)
    time.sleep(0.1)
    hotkey_paste()

    print(f"已粘贴好友关键词到搜索框: {friend_keyword}")

    time.sleep(wait_after_paste)

    first_x = int(result.click_x + result_offset_x)
    first_y = int(result.click_y + result_offset_y)

    print(
        f"准备点击搜索框下方第一个结果: "
        f"x={first_x}, y={first_y}, "
        f"offset=({result_offset_x}, {result_offset_y})"
    )

    click_screen_position(first_x, first_y)
    print("已点击第一个搜索结果。")

    # 等待微信进入聊天窗口
    time.sleep(0.8)
    return True


def has_wechat_toolbar_icons(img, box, debug=False):
    """
    判断候选输入框底部左侧是否存在微信输入框工具栏图标。

    主要识别这排：
        表情 / 立方体 / 文件夹 / 剪刀 / 麦克风

    box: (x, y, w, h)，截图内部坐标
    """
    x, y, bw, bh = box
    img_h, img_w = img.shape[:2]

    # 工具栏一般在输入框底部，左侧 300 像素左右
    roi_x1 = max(0, x)
    roi_x2 = min(img_w, x + min(340, int(bw * 0.50)))

    roi_y1 = max(0, y + int(bh * 0.52))
    roi_y2 = min(img_h, y + bh)

    if roi_x2 <= roi_x1 or roi_y2 <= roi_y1:
        return False, 0

    roi = img[roi_y1:roi_y2, roi_x1:roi_x2]

    if debug:
        save_image("debug_toolbar_roi.png", roi)

    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)

    # 图标是深灰色线条，背景是白/浅灰
    dark = cv2.inRange(gray, 0, 160)

    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (4, 4))
    dark_closed = cv2.morphologyEx(dark, cv2.MORPH_CLOSE, kernel, iterations=1)

    if debug:
        save_image("debug_toolbar_dark_mask.png", dark_closed)

    contours, _ = cv2.findContours(
        dark_closed,
        cv2.RETR_EXTERNAL,
        cv2.CHAIN_APPROX_SIMPLE,
    )

    raw_boxes = []

    for cnt in contours:
        px, py, pw, ph = cv2.boundingRect(cnt)
        area = pw * ph

        # 单个图标或图标碎片大小
        if area < 15:
            continue

        if pw < 4 or ph < 4:
            continue

        if pw > 55 or ph > 55:
            continue

        center_y = py + ph // 2

        # 图标一般在工具栏偏下的位置
        if center_y < roi.shape[0] * 0.25:
            continue

        raw_boxes.append((px, py, pw, ph))

    if not raw_boxes:
        return False, 0

    raw_boxes.sort(key=lambda b: b[0])

    # 合并距离很近的碎片，避免一个图标被拆成多个轮廓
    merged = []

    for px, py, pw, ph in raw_boxes:
        if not merged:
            merged.append([px, py, px + pw, py + ph])
            continue

        last = merged[-1]

        if px - last[2] < 12:
            last[0] = min(last[0], px)
            last[1] = min(last[1], py)
            last[2] = max(last[2], px + pw)
            last[3] = max(last[3], py + ph)
        else:
            merged.append([px, py, px + pw, py + ph])

    icon_boxes = []

    for mx1, my1, mx2, my2 in merged:
        mw = mx2 - mx1
        mh = my2 - my1
        area = mw * mh

        if area < 35:
            continue

        if mw > 65 or mh > 60:
            continue

        icon_boxes.append((mx1, my1, mw, mh))

    icon_count = len(icon_boxes)

    if debug:
        debug_img = roi.copy()

        for ix, iy, iw, ih in icon_boxes:
            cv2.rectangle(debug_img, (ix, iy), (ix + iw, iy + ih), (0, 255, 0), 2)

        save_image("debug_toolbar_icon_boxes.png", debug_img)

    print(f"工具栏图标数量: {icon_count}")

    # 正常这排有 5 个左右。
    # 有时候剪刀和小箭头会合并，所以至少 4 个就算通过。
    return icon_count >= 4, icon_count


def detect_chat_input_box(img):
    """
    从副屏截图里识别微信聊天输入框。

    加强版：
    1. 先找输入框上下两条横线；
    2. 再检查输入框底部左侧是否有微信工具栏图标；
    3. 只有通过工具栏图标验证的候选，才认为是真正微信输入框。
    """
    h, w = img.shape[:2]

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    blur = cv2.GaussianBlur(gray, (3, 3), 0)

    edges = cv2.Canny(blur, 20, 70)
    save_image("debug_edges.png", edges)

    min_line_length = int(max(250, w * 0.25))

    lines = cv2.HoughLinesP(
        edges,
        rho=1,
        theta=np.pi / 180,
        threshold=80,
        minLineLength=min_line_length,
        maxLineGap=25,
    )

    line_debug = img.copy()
    horizontals = []

    if lines is not None:
        for line in lines[:, 0]:
            x1, y1, x2, y2 = map(int, line)

            # 只要水平线
            if abs(y2 - y1) > 4:
                continue

            if x2 < x1:
                x1, x2 = x2, x1
                y1, y2 = y2, y1

            y_mid = int((y1 + y2) / 2)
            line_len = x2 - x1

            # 输入框一般在屏幕下半部分
            if y_mid < h * 0.35:
                continue

            if line_len < min_line_length:
                continue

            horizontals.append((x1, y_mid, x2, line_len))
            cv2.line(line_debug, (x1, y_mid), (x2, y_mid), (0, 0, 255), 2)

    save_image("debug_hough_lines.png", line_debug)

    print(f"检测到水平线数量: {len(horizontals)}")

    candidates = []

    for top_line in horizontals:
        for bottom_line in horizontals:
            x1_top, y_top, x2_top, len_top = top_line
            x1_bottom, y_bottom, x2_bottom, len_bottom = bottom_line

            if y_bottom <= y_top:
                continue

            box_h = y_bottom - y_top

            # 输入框高度大概几十到两百多像素
            if box_h < 45:
                continue

            if box_h > max(280, h * 0.38):
                continue

            overlap_left = max(x1_top, x1_bottom)
            overlap_right = min(x2_top, x2_bottom)
            overlap = overlap_right - overlap_left

            if overlap <= 0:
                continue

            if overlap < min(len_top, len_bottom) * 0.60:
                continue

            x_left = min(x1_top, x1_bottom)
            x_right = max(x2_top, x2_bottom)
            box_w = x_right - x_left

            if box_w < max(280, w * 0.20):
                continue

            # 太宽的大概率是整个浏览器/窗口边框
            if box_w > w * 0.97:
                continue

            pad = 8
            bx = max(0, x_left - pad)
            by = max(0, y_top - pad)
            bbw = min(w - bx, box_w + pad * 2)
            bbh = min(h - by, box_h + pad * 2)

            candidate_box = (bx, by, bbw, bbh)

            # 核心：必须有微信工具栏图标
            has_icons, icon_count = has_wechat_toolbar_icons(
                img,
                candidate_box,
                debug=False,
            )

            print(
                f"候选框: x={bx}, y={by}, w={bbw}, h={bbh}, "
                f"has_icons={has_icons}, icon_count={icon_count}"
            )

            if not has_icons:
                continue

            score = (
                y_top * 2.5
                + box_w
                + overlap
                + icon_count * 300
                - abs(len_top - len_bottom) * 2
            )

            candidates.append(
                {
                    "score": score,
                    "x": bx,
                    "y": by,
                    "w": bbw,
                    "h": bbh,
                    "icon_count": icon_count,
                }
            )

    print(f"通过工具栏验证的候选输入框数量: {len(candidates)}")

    if not candidates:
        return None

    candidates.sort(key=lambda item: item["score"], reverse=True)
    best = candidates[0]

    # 保存最终候选的工具栏识别调试图
    has_wechat_toolbar_icons(
        img,
        (best["x"], best["y"], best["w"], best["h"]),
        debug=True,
    )

    return best["x"], best["y"], best["w"], best["h"]


def paste_text_to_box_from_monitor(
    text="こんにちは",
    monitor_index=2,
    no_paste=False,
):
    """
    从副屏截图识别微信聊天输入框，然后点击中间，清空并粘贴文字。
    不需要微信提前 focus。
    """
    pyautogui.FAILSAFE = True

    img, region = screenshot_monitor(monitor_index=monitor_index)

    box = detect_chat_input_box(img)

    if box is None:
        print("没有识别到微信聊天输入框")
        save_image("debug_no_box.png", img)

        print()
        print("你看这几个文件：")
        print(os.path.join(DEBUG_DIR, "debug_monitor_screenshot.png"))
        print(os.path.join(DEBUG_DIR, "debug_edges.png"))
        print(os.path.join(DEBUG_DIR, "debug_hough_lines.png"))
        return False

    x, y, bw, bh = box

    print(f"识别到微信输入框: x={x}, y={y}, w={bw}, h={bh}")

    result = img.copy()
    cv2.rectangle(result, (x, y), (x + bw, y + bh), (0, 255, 0), 2)
    cv2.putText(
        result,
        "wechat input box",
        (x, max(25, y - 10)),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.8,
        (0, 255, 0),
        2,
    )
    save_image("debug_input_result.png", result)

    # 副屏截图坐标要加上副屏的全局偏移
    screen_left = region["left"]
    screen_top = region["top"]

    # 点击输入框中间。点击后微信会自动获得焦点。
    click_x = screen_left + x + bw // 2
    click_y = screen_top + y + bh // 2

    print(f"准备点击微信输入框中间，全局坐标: x={click_x}, y={click_y}")

    if no_paste:
        print("当前是 --no-paste 模式，只识别聊天输入框，不点击、不粘贴、不发送。")
        return True

    pyperclip.copy(text)

    time.sleep(0.2)

    # 点击会让微信获得焦点
    pyautogui.click(click_x, click_y)
    time.sleep(0.3)

    # 清空旧内容
    hotkey_select_all()
    time.sleep(0.1)
    pyautogui.press("backspace")
    time.sleep(0.1)

    # 粘贴一次
    hotkey_paste()

    return True


def send_text_from_monitor(text="こんにちは", monitor_index=2, debug_send=True):
    """
    发送消息主流程：

        从副屏识别微信输入框
        点击输入框中间
        清空旧内容
        粘贴文字
        从副屏识别带语音图标辅助验证的发送按钮
        点击发送
    """
    ok = paste_text_to_box_from_monitor(
        text=text,
        monitor_index=monitor_index,
        no_paste=False,
    )

    if not ok:
        return False

    time.sleep(0.5)

    return send_button.click_send_button_from_monitor(
        monitor_index=monitor_index,
        debug=debug_send,
    )


def send_message_to_fixed_friend(
    friend_keyword: str = "ウィーエト",
    text: str = "こんにちは",
    monitor_index: int = 2,
    debug_search: bool = False,
    debug_send: bool = True,
    title_keyword: str | None = None,
    result_offset_x: int = 0,
    result_offset_y: int = 78,
    wait_after_search_paste: float = 0.8,
    taskbar_monitor_index: int = 1,
    taskbar_bottom_height: int = 80,
    taskbar_debug: bool = False,
    wait_after_taskbar_click: float = 1.2,
):
    """
    对外调用方法：给固定好友发消息。

    先用搜索框搜索并点击第一个搜索结果，再识别聊天输入框并发送消息。
    """
    ok = search_friend_and_click_first_result(
        friend_keyword=friend_keyword,
        monitor_index=monitor_index,
        debug_search=debug_search,
        title_keyword=title_keyword,
        result_offset_x=result_offset_x,
        result_offset_y=result_offset_y,
        wait_after_paste=wait_after_search_paste,
        taskbar_monitor_index=taskbar_monitor_index,
        taskbar_bottom_height=taskbar_bottom_height,
        taskbar_debug=taskbar_debug,
        wait_after_taskbar_click=wait_after_taskbar_click,
    )

    if not ok:
        return False

    return send_text_from_monitor(
        text=text,
        monitor_index=monitor_index,
        debug_send=debug_send,
    )


def main():
    parser = argparse.ArgumentParser(description="使用微信搜索框定位固定好友，并发送文字")
    parser.add_argument(
        "--text",
        "-t",
        default="こんにちは",
        help="要发送的文字",
    )
    parser.add_argument(
        "--friend-keyword",
        default="ウィーエト",
        help="搜索框里输入的固定好友关键词，默认 ウィーエト",
    )
    parser.add_argument(
        "--monitor",
        type=int,
        default=2,
        help="截图屏幕：0=所有屏幕，1=主屏，2=副屏",
    )
    parser.add_argument(
        "--title-keyword",
        default=None,
        help="可选：微信窗口标题关键词，比如 微信",
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
        help="第一个搜索结果点击点相对搜索框中心的 Y 偏移，默认 78；如果点偏了就调这个",
    )
    parser.add_argument(
        "--wait-after-search-paste",
        type=float,
        default=0.8,
        help="好友关键词粘贴后等待搜索结果出现的秒数，默认 0.8",
    )
    parser.add_argument(
        "--taskbar-monitor",
        type=int,
        default=1,
        help="如果没有识别到微信窗口，就从这个屏幕底部任务栏识别微信图标并点击。默认 1=主屏",
    )
    parser.add_argument(
        "--taskbar-bottom-height",
        type=int,
        default=80,
        help="任务栏识别时截取屏幕底部高度，默认 80 像素",
    )
    parser.add_argument(
        "--taskbar-debug",
        action="store_true",
        help="从任务栏识别微信图标时保存调试图",
    )
    parser.add_argument(
        "--wait-after-taskbar-click",
        type=float,
        default=1.2,
        help="点击任务栏微信图标后等待几秒再重新识别搜索框，默认 1.2 秒",
    )
    parser.add_argument(
        "--skip-friend-search",
        action="store_true",
        help="跳过搜索好友，直接识别当前聊天输入框并发送",
    )
    parser.add_argument(
        "--no-paste",
        action="store_true",
        help="只识别当前聊天输入框，不点击好友、不粘贴、不发送",
    )
    parser.add_argument(
        "--debug-search",
        action="store_true",
        help="保存搜索框识别调试图",
    )
    parser.add_argument(
        "--no-debug-send",
        action="store_true",
        help="发送按钮识别时不保存调试图",
    )

    args = parser.parse_args()

    print("3 秒后开始。微信不需要获得焦点，但必须在副屏上可见、不能被挡住。")
    time.sleep(3)

    if args.no_paste:
        paste_text_to_box_from_monitor(
            text=args.text,
            monitor_index=args.monitor,
            no_paste=True,
        )
        return

    if not args.skip_friend_search:
        ok = search_friend_and_click_first_result(
            friend_keyword=args.friend_keyword,
            monitor_index=args.monitor,
            debug_search=args.debug_search,
            title_keyword=args.title_keyword,
            result_offset_x=args.result_offset_x,
            result_offset_y=args.result_offset_y,
            wait_after_paste=args.wait_after_search_paste,
            taskbar_monitor_index=args.taskbar_monitor,
            taskbar_bottom_height=args.taskbar_bottom_height,
            taskbar_debug=args.taskbar_debug,
            wait_after_taskbar_click=args.wait_after_taskbar_click,
        )

        if not ok:
            print("搜索并点击好友失败，停止发送。")
            return

    send_text_from_monitor(
        text=args.text,
        monitor_index=args.monitor,
        debug_send=not args.no_debug_send,
    )


if __name__ == "__main__":
    main()
