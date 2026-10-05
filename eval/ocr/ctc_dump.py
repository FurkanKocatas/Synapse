"""Per text line of each page: PP-OCRv6's detection box and its recogniser's frame-by-frame
character distributions (top k), so decoders (greedy, beam search with a language model,
ctc_decode.py) can be compared offline without running the recogniser again.

    python eval/ocr/ctc_dump.py --images DIR --out DIR [--rec-dir DIR | --rec-model NAME]
                                [--topk 12] [--device gpu]

Writes OUT/<page>.npz: boxes (n, 4), and per line i arrays idx_i (T, k) int32 and prob_i (T, k)
float16; OUT/chars.txt holds the recogniser's character list (index 0 is the CTC blank).
``--rec-dir`` takes a fine-tuned recogniser exported for inference.

Detection and line crops are those of PaddleOCR's OCR pipeline: the page is not shrunk (the
detection module alone scales the long side down to 960 pixels, which loses small print on
150 dpi scans) and each line is cut out along its tilted rectangle, not its upright bounding
box. Needs paddleocr 3.x; the distributions are taken from the predictor's post-processing
step and the crops from the pipeline's cropping component, neither of them a public API.
"""

import argparse
import time
from pathlib import Path

import numpy as np
from paddleocr import TextDetection, TextRecognition
from paddlex.inference.pipelines.components.common.crop_image_regions import CropByPolys
from PIL import Image

MIN_SIDE = 4  # pixels; thinner detections are specks, not text
# PaddleOCR's OCR pipeline settings for PP-OCRv6 (paddlex configs/pipelines/OCR.yaml)
DETECTION = {
    "limit_side_len": 64,
    "limit_type": "min",
    "thresh": 0.3,
    "box_thresh": 0.6,
    "unclip_ratio": 1.5,
}


def recognizer(name: str, directory: str | None, device: str):
    """The recogniser, its post-processing step wrapped so that each call's frame
    distributions land in the returned list, and its character list."""
    kwargs = {"model_dir": directory} if directory else {}
    rec = TextRecognition(model_name=name, device=device, **kwargs)
    predictor = rec.paddlex_predictor
    predictor = getattr(predictor, "_predictor", predictor)
    post = predictor.post_op
    captured: list[np.ndarray] = []
    original = post.__call__

    def capture(pred, **kwargs):
        captured.append(np.array(pred[0]))
        return original(pred, **kwargs)

    predictor.post_op = capture
    return rec, captured, post.character


def main() -> None:
    options = argparse.ArgumentParser()
    options.add_argument("--images", type=Path, required=True)
    options.add_argument("--out", type=Path, required=True)
    options.add_argument("--rec-dir")
    # another PaddleOCR recogniser by name, e.g. latin_PP-OCRv5_mobile_rec (a voice for the vote)
    options.add_argument("--rec-model", default="PP-OCRv6_medium_rec")
    options.add_argument("--topk", type=int, default=12)
    options.add_argument("--device", default="cpu")
    # the detector reads the page with its long side at most this (pixels); memory, blur
    options.add_argument("--det-max-side", type=int)
    args = options.parse_args()
    detection = dict(DETECTION)
    if args.det_max_side:
        detection.update(limit_side_len=args.det_max_side, limit_type="max")
    det = TextDetection(model_name="PP-OCRv6_medium_det", device=args.device, **detection)
    rec, captured, characters = recognizer(args.rec_model, args.rec_dir, args.device)
    crop_lines = CropByPolys(det_box_type="quad")
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "chars.txt").write_text("\n".join(characters), encoding="utf-8")
    images = sorted(p for p in args.images.iterdir() if p.suffix in {".png", ".jpg"})
    todo = [p for p in images if not (args.out / f"{p.stem}.npz").exists()]
    start = time.time()
    for n, path in enumerate(todo, 1):
        page = np.asarray(Image.open(path).convert("RGB"))[:, :, ::-1].copy()  # BGR, as read
        boxes, polys = [], []
        for poly in det.predict(page)[0]["dt_polys"]:
            xs, ys = [float(p[0]) for p in poly], [float(p[1]) for p in poly]
            box = (max(0, int(min(xs))), max(0, int(min(ys))), int(max(xs)) + 1, int(max(ys)) + 1)
            if box[2] - box[0] < MIN_SIDE or box[3] - box[1] < MIN_SIDE:
                continue
            boxes.append(box)
            polys.append(poly)
        crops = crop_lines(page, polys) if polys else []
        arrays = {"boxes": np.array(boxes, dtype=np.int32).reshape(-1, 4)}
        for i, crop in enumerate(crops):
            captured.clear()
            list(rec.predict(crop, batch_size=1))  # one line a call: a batch pads to the widest
            probs = captured[-1][0]
            # the k likeliest characters per frame, likeliest first; a full sort of the whole
            # character set took most of the time (6 s of 7 per page on a GPU)
            top = np.argpartition(-probs, args.topk, axis=1)[:, : args.topk]
            kept = np.take_along_axis(probs, top, axis=1)
            order = np.argsort(-kept, axis=1, kind="stable")
            top, kept = np.take_along_axis(top, order, 1), np.take_along_axis(kept, order, 1)
            arrays[f"idx_{i}"] = top.astype(np.int32)
            arrays[f"prob_{i}"] = kept.astype(np.float16)
        np.savez_compressed(args.out / f"{path.stem}.npz", **arrays)
        if n % 10 == 0 or n == len(todo):
            print(f"{n}/{len(todo)} {(time.time() - start) / n:.1f} s/page", flush=True)


if __name__ == "__main__":
    main()
