"""
main.py
-------
Studio Rocky - AI ミックス処理サーバー（FastAPI）

スマホアプリから「伴奏(インスト)」と「歌声」の2つの音声ファイルを受け取り、
ノイズ除去・音ズレ補正・コンプ/リミッターでプロ品質にミックスして返す。

起動方法:
    uvicorn main:app --host 0.0.0.0 --port 8000

動作確認（別ターミナルから）:
    curl -X POST http://localhost:8000/api/mix-audio \
        -F "vocal=@vocal.wav" -F "backing=@backing.mp3" \
        -o mixed.wav
"""

from __future__ import annotations

import os
import shutil
import tempfile
import traceback
import uuid
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from audio_mix import AudioProcessingError, mix_vocal_and_backing

app = FastAPI(
    title="Studio Rocky Mix API",
    version="1.0.0",
    description="歌声と伴奏を受け取り、自動で整列・加工・ミックスして返すAPI",
)

# スマホアプリなど別オリジンから叩けるように CORS を許可（本番では絞ってください）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["POST", "GET"],
    allow_headers=["*"],
)

# 受け付ける拡張子と、1ファイルの最大サイズ
ALLOWED_EXT = {".wav", ".mp3", ".m4a", ".aac", ".ogg", ".flac"}
MAX_BYTES = 60 * 1024 * 1024  # 60MB
MEDIA_TYPES = {"wav": "audio/wav", "mp3": "audio/mpeg"}


@app.get("/")
def health() -> dict:
    """稼働確認用。ブラウザで開くと JSON が返る。"""
    return {
        "status": "ok",
        "service": "studio-rocky-mix",
        "endpoint": "/api/mix-audio (POST)",
    }


def _save_upload(up: UploadFile, dst_dir: str) -> str:
    """アップロードファイルを検証してテンポラリに保存し、そのパスを返す。"""
    ext = Path(up.filename or "").suffix.lower()
    if ext not in ALLOWED_EXT:
        raise HTTPException(
            status_code=400,
            detail=f"未対応の形式です: {ext or '不明'}"
            f"（対応: {', '.join(sorted(ALLOWED_EXT))}）",
        )
    data = up.file.read()
    if not data:
        raise HTTPException(status_code=400, detail=f"ファイルが空です: {up.filename}")
    if len(data) > MAX_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"ファイルが大きすぎます（最大 {MAX_BYTES // 1024 // 1024}MB）: {up.filename}",
        )
    path = os.path.join(dst_dir, f"{uuid.uuid4().hex}{ext}")
    with open(path, "wb") as f:
        f.write(data)
    return path


@app.post("/api/mix-audio")
async def mix_audio(
    vocal: UploadFile = File(..., description="ユーザーの歌声（wav/mp3/m4a など）"),
    backing: UploadFile = File(..., description="伴奏インスト（wav/mp3/m4a など）"),
    output_format: str = Query("wav", pattern="^(wav|mp3)$", description="出力形式"),
    vocal_lead_db: float = Query(
        3.0, ge=-6.0, le=12.0, description="歌を伴奏より何dB前に出すか"
    ),
):
    """
    2つの音源を受け取り、加工・整列・ミックスした1ファイルを返す。
    - 成功: 音声ファイル（Content-Disposition で添付）
    - 失敗: JSON でエラー内容
    補正したズレ量は X-Corrected-Ms ヘッダで確認できる。
    """
    # 出力ファイルまで安全に扱うため、リクエストごとの作業ディレクトリを作る
    work_dir = tempfile.mkdtemp(prefix="srmix_")
    cleanup = BackgroundTask(shutil.rmtree, work_dir, ignore_errors=True)
    try:
        vocal_path = _save_upload(vocal, work_dir)
        backing_path = _save_upload(backing, work_dir)
        out_path = os.path.join(work_dir, f"studio_rocky_mix.{output_format}")

        info = mix_vocal_and_backing(
            vocal_path=vocal_path,
            backing_path=backing_path,
            out_path=out_path,
            vocal_lead_db=vocal_lead_db,
            output_format=output_format,
        )

        return FileResponse(
            info["output_path"],
            media_type=MEDIA_TYPES.get(output_format, "application/octet-stream"),
            filename=f"studio_rocky_mix.{output_format}",
            headers={
                "X-Corrected-Ms": str(info["corrected_ms"]),
                "X-Duration-Sec": str(info["duration_sec"]),
            },
            background=cleanup,  # レスポンス送信後に作業ディレクトリを削除
        )

    except HTTPException:
        shutil.rmtree(work_dir, ignore_errors=True)
        raise
    except AudioProcessingError as e:
        shutil.rmtree(work_dir, ignore_errors=True)
        raise HTTPException(status_code=422, detail=f"音声処理に失敗しました: {e}")
    except Exception as e:  # noqa: BLE001
        shutil.rmtree(work_dir, ignore_errors=True)
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"サーバー内部エラー: {e}")
