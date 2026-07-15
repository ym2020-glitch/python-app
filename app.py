"""
app.py
------
Studio Rocky - AI ミックス処理サーバー（FastAPI / Render 用エントリ）

スマホアプリから「伴奏」と「歌声」を受け取り、ノイズ除去・音ズレ自動補正・
コンプ/リミッターでプロ品質にミックスして返す。

Render の起動コマンド:
    uvicorn app:app --host 0.0.0.0 --port $PORT
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

app = FastAPI(title="Studio Rocky Mix API", version="2.0.0")

# スマホアプリなど別オリジンから叩けるよう許可（本番は必要に応じて絞る）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["POST", "GET"],
    allow_headers=["*"],
)

ALLOWED_EXT = {".wav", ".mp3", ".m4a", ".aac", ".ogg", ".flac", ".webm"}
MAX_BYTES = 60 * 1024 * 1024  # 60MB


@app.get("/")
def health() -> dict:
    return {"status": "ok", "service": "studio-rocky-mix", "endpoint": "/api/mix-audio (POST)"}


def _save_upload(up: UploadFile, dst_dir: str) -> str:
    ext = Path(up.filename or "").suffix.lower()
    if ext not in ALLOWED_EXT:
        raise HTTPException(
            status_code=400,
            detail=f"未対応の形式です: {ext or '不明'}（対応: {', '.join(sorted(ALLOWED_EXT))}）",
        )
    data = up.file.read()
    if not data:
        raise HTTPException(status_code=400, detail=f"ファイルが空です: {up.filename}")
    if len(data) > MAX_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"ファイルが大きすぎます（最大 {MAX_BYTES // 1024 // 1024}MB）",
        )
    path = os.path.join(dst_dir, f"{uuid.uuid4().hex}{ext}")
    with open(path, "wb") as f:
        f.write(data)
    return path


@app.post("/api/mix-audio")
async def mix_audio(
    vocal: UploadFile = File(..., description="ユーザーの歌声"),
    backing: UploadFile = File(..., description="伴奏インスト"),
    vocal_lead_db: float = Query(3.0, ge=-6.0, le=12.0, description="歌を伴奏より前に出す量(dB)"),
    manual_offset_ms: float = Query(0.0, ge=-400.0, le=400.0, description="ズレ手動微調整(ms)"),
):
    """2音源を受け取り、整列・加工・ミックスした WAV を返す。"""
    work_dir = tempfile.mkdtemp(prefix="srmix_")
    cleanup = BackgroundTask(shutil.rmtree, work_dir, ignore_errors=True)
    try:
        vocal_path = _save_upload(vocal, work_dir)
        backing_path = _save_upload(backing, work_dir)
        out_path = os.path.join(work_dir, "studio_rocky_mix.wav")

        info = mix_vocal_and_backing(
            vocal_path=vocal_path,
            backing_path=backing_path,
            out_path=out_path,
            vocal_lead_db=vocal_lead_db,
            manual_offset_ms=manual_offset_ms,
        )
        return FileResponse(
            info["output_path"],
            media_type="audio/wav",
            filename="studio_rocky_mix.wav",
            headers={
                "X-Corrected-Ms": str(info["corrected_ms"]),
                "X-Duration-Sec": str(info["duration_sec"]),
            },
            background=cleanup,
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
