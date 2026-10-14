# OCR accuracy check

From the repository root, run:

```powershell
python ocr_accuracy_test/check_ocr.py
```

Uses the same CnOCR worker as the message reader on `a.png` inside this test folder. Results are saved in `output/`: `recognized.txt`, `results.json` (text, confidence, positions), `annotated.png`, and `report.json`.

All detected text is recognized by default. Accuracy comparison is optional: provide `--expected path/to/reference.txt` with a manually transcribed reference for the actual image. The existing `expected.txt` belongs to the earlier screenshot containing only the Send label; replace it before using it with another image.

Confidence is the model's score, not measured accuracy. The report compares reading-order text to the reference after removing whitespace, using exact match and character error rate (CER = Levenshtein distance / reference character count). CER can exceed 100% when extra text is recognized. This single small screenshot measures this sample only, not general OCR accuracy.

For another image: `python ocr_accuracy_test/check_ocr.py --image path/to/image.png --expected path/to/reference.txt`. If the reference file does not exist, only recognition results are produced.
