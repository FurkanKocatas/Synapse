# OCR engines for the benchmark (eval/ocr/README.md). Not part of the product image.
#   docker build -t synapse-ocr-bench eval/ocr
ARG PYTHON=python:3.14-slim-trixie@sha256:51dafde81dbdb6ebde285137a295cf18a47ca95234fe388a343719cb97305b3d
FROM ${PYTHON}

# Debian's Tesseract with its own Turkish and English models (the "tessdata" set).
RUN apt-get update \
 && apt-get install --yes --no-install-recommends tesseract-ocr tesseract-ocr-tur tesseract-ocr-eng \
 && rm -rf /var/lib/apt/lists/*

# The two other official model sets, pinned by release and checksum.
ADD --checksum=sha256:e0c3338dc17503dc7d335a507c9ae01b2b46cfd07561171e1e1ac55d85e8e438 \
    https://github.com/tesseract-ocr/tessdata_best/raw/4.1.0/tur.traineddata /models/best/tur.traineddata
ADD --checksum=sha256:8280aed0782fe27257a68ea10fe7ef324ca0f8d85bd2fd145d1c2b560bcb66ba \
    https://github.com/tesseract-ocr/tessdata_best/raw/4.1.0/eng.traineddata /models/best/eng.traineddata
ADD --checksum=sha256:7393381111e1152420fc4092cb44eef4237580d21b92bf30d7d221aad192c6b7 \
    https://github.com/tesseract-ocr/tessdata_fast/raw/4.1.0/tur.traineddata /models/fast/tur.traineddata
ADD --checksum=sha256:7d4322bd2a7749724879683fc3912cb542f19906c83bcc1a52132556427170b2 \
    https://github.com/tesseract-ocr/tessdata_fast/raw/4.1.0/eng.traineddata /models/fast/eng.traineddata

# RapidOCR asks for the desktop OpenCV build, which needs libGL; the headless one is enough.
RUN pip install --no-cache-dir rapidocr==3.9.2 onnxruntime==1.24.* pillow \
 && pip uninstall --yes opencv-python \
 && pip install --no-cache-dir opencv-python-headless

WORKDIR /bench
ENTRYPOINT ["python", "/bench/run.py"]
