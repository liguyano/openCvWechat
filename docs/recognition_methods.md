# Recognition Methods

This guide describes the recognition methods implemented in this repository. It covers the desktop WeChat sender, the standalone conversation-list recognizer, taskbar icon detection, and the article capture tools. Thresholds below describe the current implementation; they are pixel-based heuristics rather than guarantees across all WeChat versions or display scales.

## 1. Overview

| Target | Source | Main method |
| --- | --- | --- |
| WeChat window and navigation bar | `wechat_search_box_recognizer_click.py`, `friend_list_ocr.py` | Windows window enumeration and visual scoring |
| Search box | `wechat_search_box_recognizer_click.py` | Bright rectangle, magnifier, and neighboring plus icon |
| First friend search result | `main.py` | Fixed offset from the search box; no result recognition |
| Conversation avatars and rows | `friend_list_ocr.py` | Color, darkness, edges, and horizontal projection |
| Selected conversation row | `friend_list_ocr.py` | Green rectangle and estimated row spacing |
| Conversation names | `friend_list_ocr.py` | CnOCR on cropped and enlarged name regions |
| Chat input box | `main.py` | Horizontal line pairs, toolbar contours, and right-side controls |
| Send button | `send_button.py` | Green rectangle with a voice icon to its left |
| WeChat taskbar icon | `taskbar_wechat_clicker.py` | Green regions with white chat-bubble features |
| Generic taskbar icon | `taskbar_icon_match_clicker.py` | Template matching at multiple scales |
| Article result thumbnails | `wechatArtical/autoGetImg.py` | Colored thumbnail contours and estimated title positions |
| Blank focus area | Both article scripts | Brightness, low variation, and sparse edges |
| Scrollbar thumb | Both article scripts | Gray mask and narrow vertical contours |
| Article images and video covers | Both article scripts | Row/column projections of a media mask |
| Duplicate image crops | Both article scripts | Perceptual hash and Hamming distance |

The GUI files configure and schedule operations. They do not implement separate image recognition algorithms. In this guide, "both article scripts" refers to `wechatArtical/autoGetImg.py` and `wechatArtical/wechat_article_capture.py`.

## 2. Screenshots and Coordinates

Screenshots are captured with MSS and converted from BGRA to OpenCV BGR images. Monitor index `0` represents the combined desktop; `1` is the primary monitor and `2` is the next monitor, when available. The taskbar detectors capture only a bottom strip of the selected monitor.

Distinguish three coordinate systems:

- Window coordinates: positions relative to a captured WeChat window.
- Screenshot coordinates: positions relative to a monitor or other captured region.
- Desktop coordinates: absolute positions used for mouse clicks.

For a detected rectangle `(x, y, width, height)`, its absolute center is:

```text
click_x = capture_region.left + x + width // 2
click_y = capture_region.top  + y + height // 2
```

When a window is cropped from a monitor screenshot, add its crop offset before adding the monitor origin. Monitor origins can be negative. Windows DPI-awareness helpers reduce screenshot/click mismatches, but fixed pixel sizes still make display scaling relevant.

## 3. WeChat Window and Navigation Bar

**Entry points:** `find_wechat_window_on_monitor()`, `score_wechat_window()`, and `has_wechat_left_nav_icons()` in the search-box and conversation-list recognizers.

The recognizers enumerate Windows windows, filter candidates by monitor overlap and minimum size, and optionally require a title containing `title_keyword`. They capture candidate rectangles and score their visible appearance.

The search-box recognizer checks the narrow left navigation strip for:

1. A light gray, low-saturation background.
2. A small green chat icon near the upper part of the strip.
3. Multiple dark icon contours arranged vertically. Nearby contour centers are merged to avoid counting fragments of one icon separately.

A passing navigation strip is required for a positive window score. A bright search area and variation in the conversation list add bonuses. The highest-scoring candidate is selected. The conversation-list recognizer has its own similar implementation; its thresholds should be inspected separately when tuning it.

**Limitations:** A screenshot contains whatever is visibly covering the window. Occlusion, dark themes, small windows, and changed navigation layouts can invalidate these checks. Window-title filtering helps narrow candidates but does not replace visual validation.

## 4. Search Box, Plus Icon, and Magnifier

**Entry point:** `WeChatSearchBoxRecognizer.detect_search_box_in_window()`.

The detector searches the upper-left region of the selected window, approximately `x=60..390`, `y=12..90`.

### Plus icon

`find_plus_icon_candidates()` uses Gaussian blur and Hough circle detection. Dark pixels across the circle's center row and column provide evidence for the plus sign. Candidates are restricted to the right portion of the search region.

If circle detection produces no acceptable candidate, a dark mask and morphological closing generate small, approximately square contours as a fallback.

### Search rectangle

The background mask requires grayscale brightness `235..255` and HSV saturation at most `55`. Closing fills gaps and opening removes small artifacts. Rectangle candidates must be approximately `90..280` pixels wide and `20..52` pixels high.

A plus icon must lie to the right of the rectangle, within a limited gap and at a similar vertical position. Scores combine this relationship, magnifier evidence, brightness, aspect ratio, and width.

### Magnifier

`has_magnifier_icon()` examines the left part of the rectangle. It looks for a small circle and dark pixels near the expected lower-right handle. A weak magnifier result reduces the score; it does not always reject the rectangle.

If no bright rectangle survives, the detector estimates a search rectangle from a detected plus icon and ranks it using layout and magnifier evidence.

**Output:** `SearchBoxResult` includes the window-relative rectangle, absolute click coordinates, plus-icon position, window information, and score. Failure returns `None`.

## 5. First Friend Search Result

**Entry point:** `main.search_friend_and_click_first_result()`.

After recognizing the search box, the program clicks it, clears the existing query, pastes `friend_keyword`, and waits for results. It then clicks a fixed offset from the search-box center:

```text
result_x = search_center_x + result_offset_x
result_y = search_center_y + result_offset_y
```

The default offsets are `0` and `78` pixels. `wait_after_paste` controls the delay in this function; the public sender exposes it as `wait_after_search_paste`.

This step does not read the result name or verify the selected friend's identity. If the search box is initially unavailable, the workflow can activate WeChat through its taskbar icon and retry. Incorrect result clicks should be investigated through offsets, search timing, and actual result order.

## 6. Conversation Avatars, Rows, and Selected Row

**Entry point:** `WeChatFriendListRecognizer.refresh()` in `friend_list_ocr.py`.

### Avatar centers

`find_avatar_centers_in_wechat_window()` examines the avatar column, approximately `x=65..135`, below `y=75`. It combines saturated pixels, dark pixels, and dilated Canny edges into a mask. Morphological closing connects nearby features.

The mask is summed across each row and smoothed. Consecutive active rows form avatar segments; size checks and nearby-center merging produce vertical avatar centers. This recognizes occupied avatar regions, not the identity of a person in an avatar.

### Conversation rows

`build_rows_from_avatar_centers()` creates rectangles around those centers using `row_height`, which defaults to `72`. It constrains rows to the conversation-list column and removes near-duplicates.

### Selected-row fallback

If fewer than three rows are found, `find_selected_row_center_in_list()` searches the list for a wide green rectangle. HSV thresholding, closing, and shape filters identify the selected row. `build_rows_from_selected_center()` estimates other rows above and below it using the configured row height.

**Limitations:** Estimated rows assume uniform spacing. Different UI scaling, unusually sized avatars, or a selected-row color change can affect results.

## 7. Conversation Name OCR

**Entry point:** `ocr_name_from_row()` in `friend_list_ocr.py`.

For each row, the recognizer crops the upper name line, excluding the avatar on the left and timestamp area on the right. It enlarges the crop by a factor of three using cubic interpolation and adds a white border.

CnOCR is initialized lazily. The recognizer prefers `ocr_for_single_line()` and falls back to `ocr()` when needed. `collect_cnocr_texts()` normalizes supported nested OCR output formats into text/confidence pairs.

Text cleanup removes whitespace and certain leading artifacts. Text pieces passing `score_threshold` (default `0.20`) are combined. Name validation rejects empty strings, several common UI labels, and names longer than 35 characters.

With `keep_all_rows=True`, rows with invalid names remain in the results with an empty name. `FriendPosition` retains row geometry, absolute click coordinates, raw OCR text, and confidence information. OCR confidence is not proof that a recognized name is correct.

This standalone OCR pipeline is separate from the sender's fixed-offset search-result click.

## 8. Chat Input Box and Toolbar Controls

**Entry points:** `paste_text_to_box_from_monitor()` and `detect_chat_input_box()` in `main.py`.

The paste workflow attempts to obtain the WeChat window region through the search-box recognizer and crop the monitor image to that region. Valid crop dimensions must exceed `300 x 250`. If window recognition raises an exception, the function stops. If a usable region is not supplied, the current code can retain the full monitor image.

### Primary method: horizontal line pairs

The detector converts the image to grayscale, blurs it, and runs Canny followed by `HoughLinesP`. It keeps long, nearly horizontal lines below the upper part of the image. Top/bottom pairs must have a plausible vertical separation, sufficient horizontal overlap, and a suitable width.

Each padded candidate must pass two additional checks:

- `has_wechat_toolbar_icons()` thresholds dark pixels in the lower-left portion, closes gaps, merges nearby contour fragments, and requires at least four icon-like groups.
- `has_wechat_right_controls()` applies Canny and closing to the lower-right area and requires at least two suitable contours.

These checks detect layout and contour groups. They do not classify each toolbar symbol by its semantic meaning, and the right-control check does not strictly prove a particular button is present.

Candidates are ranked by vertical position, width, line overlap, icon/control counts, and similarity of line lengths.

### Fallback: toolbar bands

If no line pair passes, a dark-pixel projection in the lower 32% of the image identifies horizontal bands. The detector estimates an input rectangle from these bands and requires the same toolbar and right-control checks.

**Output:** A rectangle or `None`. The paste workflow translates coordinates, clicks the input region, clears existing text, and pastes the new message.

## 9. Send Button and Voice Icon

**Entry points:** `detect_green_send_button()` and `has_voice_icon_left_of_button()` in `send_button.py`.

The send detector examines the entire supplied screenshot. It does not require the WeChat window to be in the monitor's lower-right corner.

1. Convert to HSV and select green pixels from `[35, 60, 80]` to `[95, 255, 255]`.
2. Apply closing and dilation with a `5 x 5` kernel.
3. Extract rectangle candidates with width `45..110`, height `18..55`, aspect ratio `1.5..4.5`, and bounding-box area at least `500`.
4. Require voice-icon evidence in a region to the left of the candidate.

The voice check first uses Hough circles with radii `6..18`, constrained to a similar vertical position. If that fails, it thresholds dark pixels, applies opening, and requires at least two small contour parts.

Passing buttons are ranked with:

```text
score = y * 8 + x * 3 + bounding_box_area * 0.1
```

The click function adds the screenshot origin and clicks the selected rectangle's center. A successful return means that detection and the click were performed; it does not verify message delivery. The button label is not read with OCR, and icon-like shapes near another green rectangle can still cause false positives. A disabled, non-green button will not pass the green mask.

## 10. Taskbar Icon Recognition

### WeChat-specific color and shape method

**Source:** `taskbar_wechat_clicker.py`, class `TaskbarWeChatClicker`.

The detector captures the bottom `80` pixels by default. Green HSV contours are filtered and nearby boxes are merged. Candidate scores consider size, square-like proportions, green coverage, white coverage, and white blobs resembling chat bubbles. Candidates scoring below `5.0` are rejected; the highest remaining score wins.

This method requires no template image, but other green/white icons may resemble WeChat. The capture assumes a visible taskbar along the bottom of the selected monitor.

### Generic template method

**Source:** `taskbar_icon_match_clicker.py`, class `TaskbarIconMatchClicker`.

The detector loads an icon image and searches a bottom strip, `90` pixels high by default. It tries scales from `0.70` to `1.35` in steps of `0.05`, always including `1.0`.

Transparent PNG alpha becomes a binary mask. Masked matching uses `TM_CCORR_NORMED`; unmasked matching uses `TM_CCOEFF_NORMED`. Non-finite matching values are replaced before choosing the maximum. The best match must meet `threshold`, default `0.72`.

This method is useful for a known icon appearance. A changed icon, unsuitable template background, or size outside the scale range can lower accuracy.

## 11. Article Search Results

**Source:** `wechatArtical/autoGetImg.py`, function `detect_search_result_click_points()`.

The batch tool searches a central-left part of the screenshot for colored thumbnail regions using saturation and brightness thresholds. Closing joins fragments; contour size, aspect ratio, and area checks reject unsuitable regions. Candidates at similar vertical positions are merged.

Title click points are estimated from thumbnail positions using `RESULT_TITLE_X_OFFSET` and `RESULT_TITLE_Y_OFFSET`. Closely spaced points are removed and results are ordered vertically. If no thumbnail is recognized, configured proportional fallback points are used.

The method does not read article titles or URLs. Browser zoom and result layouts affect both thumbnail detection and offset-based clicks.

## 12. Blank Areas for Article Focus

**Sources:** Both article scripts, functions `find_safe_blank_point()` and `visual_click_blank_area()`.

The detector scans patches on a grid. It accepts bright patches with low grayscale standard deviation and a low Canny edge ratio. Scores favor bright, uniform areas toward the sides and away from extreme vertical positions. The right edge is partly excluded.

If no patch passes, a proportional fallback location is returned. This estimates a blank focus point; it does not guarantee that the point is non-interactive. Tune the `SAFE_*` constants and inspect `safe_click_debug.png` when a focus click opens an image or link.

## 13. Scrollbar Thumb and Bottom Detection

**Sources:** Both article scripts, functions `detect_scrollbar_thumb()` and `get_scrollbar_status()`.

A configured scrollbar strip is converted to grayscale. Pixels within `SCROLLBAR_GRAY_MIN..SCROLLBAR_GRAY_MAX` form a mask, which is closed before contour extraction. Thumb candidates must be narrow, sufficiently tall, and large enough. Ranking favors area, height, and position toward the right.

For the selected thumb:

```text
bottom_gap = strip_height - (thumb_y + thumb_height)
at_bottom = bottom_gap <= SCROLLBAR_BOTTOM_MARGIN
```

No detected thumb produces `None` information rather than evidence that scrolling has reached the bottom. Auto-hidden scrollbars, wrong capture strips, and unusual scrollbar colors require separate handling or configuration changes.

## 14. Article Images and Video Covers

**Sources:** Both article scripts, function `detect_image_regions()`.

The media mask combines saturated pixels, dark pixels, and Canny edges. It excludes the scrollbar-side strip and a small top margin. Row projections identify sufficiently long active bands; column projections estimate each band's horizontal extent.

Candidate crops are filtered by minimum width, height, area, and aspect ratio. A media score combines colorful-pixel ratio, dark-pixel ratio, edge density, and grayscale variation. Nearby boxes are merged; near-full-screen boxes are rejected. Optional edge filtering skips partially visible crops. The result count is limited by `MAX_IMAGES_PER_SHOT`.

This detects visually dense regions such as photographs, video covers, and QR-code images. It does not classify their contents or decode QR codes. Text-heavy regions may pass, while low-contrast images may be missed. Screenshots also preserve the displayed resolution rather than downloading original media.

## 15. Duplicate Image Detection

**Sources:** Both article scripts, functions `image_phash()`, `hamming_distance()`, and `is_duplicate()`.

Each crop is converted to grayscale and resized to `32 x 32`. A discrete cosine transform produces an `8 x 8` low-frequency block. Thresholding against the median of its `[1:, 1:]` sub-block creates a 64-bit signature.

The signature is compared with previously saved hashes. A Hamming distance at or below `DUP_HASH_THRESHOLD` marks the crop as a duplicate. Very small crops are also skipped.

This is approximate visual deduplication. Similar-looking distinct images can collide, and different partial crops of one image can have different hashes.

## 16. Debugging and Tuning

| Symptom | Inspect first | Parameters or assumptions to review |
| --- | --- | --- |
| WeChat window not found | `debug_search_box_window_scores.txt`, navigation masks | Monitor, title filter, visibility, navigation geometry |
| Search box not found | `debug_search_box_top_roi.png`, `debug_search_box_light_mask.png`, `debug_search_box_candidates.png` | Brightness mask, ROI, plus-icon alignment, scale |
| Wrong search result clicked | Search-box result and actual result list | Result offsets, wait time, result order |
| Conversation rows missing | Avatar-column mask and `debug_friend_rows.png` | Avatar ROI, projection thresholds, row height |
| Names inaccurate | `ocr_name_raw_*.png`, `ocr_name_input_*.png`, `ocr_name_result_*.txt` | Name crop, OCR model support, confidence threshold |
| Input box missing or incorrect | `debug_edges.png`, `debug_hough_lines.png`, toolbar debug images | Window crop, line filters, toolbar/control geometry |
| Send button missing | `debug_send_button_mask.png`, `debug_send_candidates_with_voice_check.png`, voice-icon debug images | Enabled button color, candidate size, voice icon |
| Taskbar icon missing | Taskbar masks or template-match debug images | Monitor, bottom-strip height, template, matching scales |
| Article regions missing or excessive | `mask_*.png` and annotated crops | `ROW_THRESHOLD`, `COL_THRESHOLD`, `MIN_IMAGE_*`, media score |
| Scroll completion incorrect | `scrollbar_*.png` | Capture strip, gray range, thumb size, bottom margin |
| Excessive duplicate rejection | Saved crops and hashes | `DUP_HASH_THRESHOLD`, crop consistency |

Debug images are generally written to `debug_output/` for the desktop recognizers and to the configured output/debug directories for the article tools. Some paths save intermediate images even when debug mode is disabled. Repeated runs can overwrite files, so preserve a failing run's screenshots before rerunning.

Tune one condition at a time against a saved failing screenshot. Include negative examples, such as an unrelated green icon or an empty screenshot, so improvements in recall do not silently introduce false positives. Detection functions can be exercised on saved images without calling the click or send entry points.
