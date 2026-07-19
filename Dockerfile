# Studio Rocky かんたん録音サーバー用イメージ（超軽量）
# ffmpeg も重いライブラリも不要。Flask + gunicorn だけ。
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PORT=8000
CMD ["sh", "-c", "gunicorn app:app --bind 0.0.0.0:${PORT} --workers 1 --timeout 120"]
