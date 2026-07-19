"""
Studio Rocky - かんたん録音サーバー (Flask / 超軽量版)
--------------------------------------------------
新方針:
  イヤホンを外し、スピーカーから伴奏を流しながら歌う。
  スマホのマイクが「伴奏＋歌声」を【1つの音声ファイルとして一括録音】する。
  → 2つの音を後で合成しないので、音ズレは物理的に起こらない。

このサーバーの役割は「録音ファイルを受け取って保存」「保存したファイルを返す」だけ。
音声合成・遅延補正・重い処理は一切しない（Render 無料枠でも軽々動く）。

Render 起動コマンド:
    gunicorn app:app --bind 0.0.0.0:$PORT
"""

import os
import uuid

from flask import Flask, jsonify, request, send_from_directory

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.join(BASE_DIR, "recordings")
os.makedirs(UPLOAD_DIR, exist_ok=True)

ALLOWED_EXT = {".webm", ".wav", ".ogg", ".m4a", ".mp4"}

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 40 * 1024 * 1024  # アップロード上限 40MB


@app.route("/")
def index():
    """録音ページ（templates/index.html）をそのまま返す。"""
    return send_from_directory(os.path.join(BASE_DIR, "templates"), "index.html")


@app.route("/health")
def health():
    return jsonify({"status": "ok"})


@app.route("/upload", methods=["POST"])
def upload():
    """録音した「伴奏＋歌声」の1ファイルを受け取って保存する。"""
    f = request.files.get("audio")
    if f is None or f.filename == "":
        return jsonify({"error": "音声ファイルがありません"}), 400

    ext = os.path.splitext(f.filename)[1].lower()
    if ext not in ALLOWED_EXT:
        ext = ".webm"  # 不明な拡張子は webm 扱い
    name = f"{uuid.uuid4().hex}{ext}"
    f.save(os.path.join(UPLOAD_DIR, name))
    return jsonify({"ok": True, "url": f"/recordings/{name}", "name": name})


@app.route("/recordings/<name>")
def get_recording(name):
    """保存した録音を返す。"""
    return send_from_directory(UPLOAD_DIR, name)


if __name__ == "__main__":
    # ローカル実行用。Render では gunicorn が起動する。
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port)
