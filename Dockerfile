# Studio Rocky ミックスサーバー用イメージ
# ffmpeg と libsndfile を含めるので、wav/mp3/m4a/webm を扱える。
FROM python:3.11-slim

# 音声の読み書きに必要なシステムライブラリ
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 依存を先に入れる（ビルドキャッシュが効く）
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# アプリ本体
COPY . .

# Render は $PORT を渡してくる（無い場合は 8000）
ENV PORT=8000
CMD ["sh", "-c", "uvicorn app:app --host 0.0.0.0 --port ${PORT}"]
