"""Isolate OCR startup and inference so the reader can enforce a deadline."""

import json
import os
from pathlib import Path
import sys


def main():
    os.environ.setdefault('OMP_NUM_THREADS', '1')
    os.environ.setdefault('MKL_NUM_THREADS', '1')
    print('OCR: importing CnOCR and its dependencies...', flush=True)
    from cnocr import CnOcr
    import cv2
    import numpy as np

    print('OCR: loading models (first use may download model files)...', flush=True)
    engine = CnOcr()
    print('OCR: models ready; reading menu text...', flush=True)
    image = cv2.imdecode(np.fromfile(sys.argv[1], dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError('Cannot read menu screenshot.')
    # CnOCR consumes RGB arrays, while screenshots are saved/loaded as BGR.
    items = engine.ocr(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))
    results = []
    for item in items:
        position = item.get('position')
        results.append(dict(text=item.get('text', ''), score=float(item.get('score', 0)),
                            position=np.asarray(position).tolist() if position is not None else []))
    Path(sys.argv[2]).write_text(json.dumps(results, ensure_ascii=False), encoding='utf-8')
    print('OCR: menu recognition finished.', flush=True)


if __name__ == '__main__':
    main()
