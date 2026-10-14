"""Run from the repository root: python ocr_accuracy_test/check_ocr.py."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

import cv2
import numpy as np


def edit_distance(a, b):
    row = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        next_row = [i]
        for j, cb in enumerate(b, 1):
            next_row.append(min(next_row[-1] + 1, row[j] + 1, row[j - 1] + (ca != cb)))
        row = next_row
    return row[-1]


def main():
    folder = Path(__file__).resolve().parent
    root = folder.parent
    parser = argparse.ArgumentParser(description='Inspect CnOCR text, confidence, and character errors.')
    parser.add_argument('--image', default=str(folder / 'a.png'))
    parser.add_argument('--expected', help='Optional reference text for accuracy measurement')
    parser.add_argument('--timeout', type=float, default=120)
    args = parser.parse_args()
    image = Path(args.image).resolve()
    output = folder / 'output'
    output.mkdir(exist_ok=True)
    result = output / 'results.json'
    result.unlink(missing_ok=True)
    print(f'Recognizing {image}; timeout {args.timeout:g}s', flush=True)
    try:
        subprocess.run([sys.executable, '-u', '-m', 'wechat_message_reader.ocr_worker',
                        str(image), str(result)], cwd=root, timeout=args.timeout, check=True)
    except subprocess.TimeoutExpired:
        parser.exit(1, 'OCR timed out. Check model downloads or increase --timeout.\n')
    except subprocess.CalledProcessError:
        parser.exit(1, 'OCR failed; see the error above.\n')
    items = json.loads(result.read_text(encoding='utf-8'))
    items.sort(key=lambda item: (min((p[1] for p in item['position']), default=0),
                                 min((p[0] for p in item['position']), default=0)))
    text = '\n'.join(item['text'] for item in items)
    (output / 'recognized.txt').write_text(text, encoding='utf-8')
    preview = cv2.imdecode(np.fromfile(image, dtype=np.uint8), cv2.IMREAD_COLOR)
    for index, item in enumerate(items, 1):
        print(f'{index}: {item["text"]} (confidence {item["score"]:.4f})')
        points = np.asarray(item['position'], dtype=np.int32)
        if points.shape == (4, 2):
            cv2.polylines(preview, [points], True, (0, 0, 255), 2)
            cv2.putText(preview, str(index), tuple(points[0]), cv2.FONT_HERSHEY_SIMPLEX,
                        .5, (0, 0, 255), 1)
    cv2.imencode('.png', preview)[1].tofile(str(output / 'annotated.png'))
    report = {'recognized_text': text, 'line_count': len(items)}
    expected_path = Path(args.expected) if args.expected else None
    if expected_path is not None and expected_path.exists():
        expected = ''.join(expected_path.read_text(encoding='utf-8-sig').split())
        actual = ''.join(text.split())
        errors = edit_distance(expected, actual)
        report.update(expected_text=expected, edit_distance=errors, exact_match=expected == actual,
                      character_error_rate=errors / len(expected) if expected else None)
        print('Comparison:', json.dumps(report, ensure_ascii=False))
    (output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'Results saved to {output}')


if __name__ == '__main__':
    main()
