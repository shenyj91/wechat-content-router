#!/usr/bin/env python3

from __future__ import annotations

import json
import sys
from pathlib import Path


def load_ocr():
    try:
        from paddleocr import PaddleOCR
    except ModuleNotFoundError as error:
        raise SystemExit(
            "PaddleOCR 未安装。请先安装 Windows OCR 依赖：\n"
            "python -m pip install paddlepaddle==3.2.0 -i https://www.paddlepaddle.org.cn/packages/stable/cpu/\n"
            'python -m pip install "paddleocr[all]"'
        ) from error

    return PaddleOCR(
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
        use_textline_orientation=False,
        engine="paddle",
    )


def extract_texts(value) -> list[str]:
    texts: list[str] = []
    if isinstance(value, dict):
        if isinstance(value.get("rec_texts"), list):
            texts.extend(str(item).strip() for item in value["rec_texts"] if str(item).strip())
            return texts
        if value.get("rec_text"):
            text = str(value.get("rec_text")).strip()
            if text:
                texts.append(text)
            return texts
        for nested in value.values():
            texts.extend(extract_texts(nested))
        return texts
    if isinstance(value, list):
        for nested in value:
            texts.extend(extract_texts(nested))
    return texts


def normalize_result_item(item) -> dict:
    data = getattr(item, "json", None)
    if callable(data):
        data = data()
    if data is None and isinstance(item, dict):
        data = item
    if data is None:
        data = {}
    payload = data.get("res", data) if isinstance(data, dict) else data
    texts = extract_texts(payload)
    return {
        "text": "\n".join(line for line in texts if line).strip()
    }


def main() -> None:
    image_paths = [str(Path(path).expanduser()) for path in sys.argv[1:]]
    if not image_paths:
        print(json.dumps({"items": []}, ensure_ascii=False, indent=2))
        return

    ocr = load_ocr()
    items = []
    for path in image_paths:
        result = ocr.predict(path)
        lines: list[str] = []
        for item in result:
            parsed = normalize_result_item(item)
            text = parsed.get("text", "").strip()
            if text:
                lines.append(text)
        items.append({
            "path": path,
            "text": "\n".join(lines).strip(),
        })

    print(json.dumps({"items": items}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
