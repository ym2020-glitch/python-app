"""
audio_mix.py
------------
「歌声」と「伴奏(インスト)」を、プロ品質に自動加工・ミックスする中核処理。
Render 無料枠でも動くよう軽量化（librosa/numba を使わず numpy+scipy で整列）。

処理:
  1) 読み込み（wav は soundfile、mp3/m4a/webm は ffmpeg 経由）→ モノ 44.1kHz
  2) 歌声のノイズ除去（noisereduce）
  3) 音ズレ自動補正（エネルギー包絡の相互相関。探索±0.35秒で拍ズレ誤検出を防止）
  4) 歌声の音づくり（ハイパス→コンプ→高域シェルフ：pedalboard）
  5) 音量バランス（歌を伴奏より前へ）
  6) ミックス＆リミッター（0dB超えなし）
  7) WAV 書き出し
"""

from __future__ import annotations

import os
from math import gcd

import numpy as np
import soundfile as sf
from scipy.signal import correlate, correlation_lags, resample_poly

SR = 44100
FRAME = 512
EPS = 1e-9


class AudioProcessingError(Exception):
    """想定内の音声処理エラー（API側で 422 として返す）。"""


# ---------- 読み込み ----------
def _resample(y: np.ndarray, from_sr: int, to_sr: int) -> np.ndarray:
    if from_sr == to_sr:
        return y.astype(np.float32)
    g = gcd(int(from_sr), int(to_sr))
    return resample_poly(y, to_sr // g, from_sr // g).astype(np.float32)


def _load_mono(path: str, sr: int = SR) -> np.ndarray:
    """音声をモノ float32 / 指定SRで読み込む。"""
    ext = os.path.splitext(path)[1].lower()
    try:
        if ext in (".wav", ".flac", ".ogg", ".aif", ".aiff"):
            y, file_sr = sf.read(path, dtype="float32", always_2d=False)
            if getattr(y, "ndim", 1) > 1:
                y = y.mean(axis=1)  # ステレオ→モノ
        else:
            # mp3 / m4a / aac / webm 等は ffmpeg 経由（pydub）
            from pydub import AudioSegment

            seg = AudioSegment.from_file(path)
            file_sr = seg.frame_rate
            samples = np.array(seg.get_array_of_samples())
            if seg.channels > 1:
                samples = samples.reshape((-1, seg.channels)).mean(axis=1)
            maxval = float(1 << (8 * seg.sample_width - 1))
            y = samples.astype(np.float32) / maxval
    except Exception as e:  # noqa: BLE001
        raise AudioProcessingError(
            f"音声の読み込みに失敗しました（ffmpeg未導入 or 破損の可能性）: {e}"
        )

    y = np.asarray(y, dtype=np.float32)
    if y.size == 0 or not np.all(np.isfinite(y)):
        raise AudioProcessingError("音声が空、または不正なデータです。")
    return _resample(y, file_sr, sr)


# ---------- 小道具 ----------
def _rms(y: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(y)) + EPS))


def _db_to_gain(db: float) -> float:
    return float(10.0 ** (db / 20.0))


def _peak_normalize(y: np.ndarray, target_dbfs: float = -1.0) -> np.ndarray:
    peak = float(np.max(np.abs(y))) if y.size else 0.0
    if peak < EPS:
        return y
    return (y * (_db_to_gain(target_dbfs) / peak)).astype(np.float32)


def _energy_env(y: np.ndarray, frame: int = FRAME) -> np.ndarray:
    n = y.size // frame
    if n < 1:
        return np.zeros(0, dtype=np.float32)
    y2 = y[: n * frame].reshape(n, frame)
    return np.sqrt(np.mean(y2 * y2, axis=1))


def _norm_env(e: np.ndarray) -> np.ndarray:
    if e.size == 0:
        return e
    e = e - e.mean()
    s = e.std()
    return (e / s) if s > EPS else e


# ---------- ② ノイズ除去 ----------
def _denoise_vocal(vocal: np.ndarray, sr: int = SR) -> np.ndarray:
    try:
        import noisereduce as nr

        reduced = nr.reduce_noise(
            y=vocal, sr=sr, stationary=False, prop_decrease=0.8
        )
        return np.asarray(reduced, dtype=np.float32)
    except Exception as e:  # noqa: BLE001
        print(f"[warn] ノイズ除去をスキップ: {e}")
        return vocal


# ---------- ③ 音ズレ自動補正 ----------
def _find_lag_samples(
    backing: np.ndarray, voice: np.ndarray, sr: int = SR, max_lag_sec: float = 0.35
) -> int:
    """
    歌声が伴奏に対して何サンプル遅れて(進んで)いるかを返す。
    正 = 歌が遅れ / 負 = 歌が早い。
    実レイテンシは 0.3秒未満なので探索を ±0.35秒に絞り、
    繰り返しの伴奏で「1拍/1小節ずれた場所」に誤ロックするのを防ぐ。
    """
    ev = _norm_env(_energy_env(voice))
    eb = _norm_env(_energy_env(backing))
    if ev.size < 4 or eb.size < 4:
        return 0

    corr = correlate(ev, eb, mode="full", method="fft")
    lags = correlation_lags(ev.size, eb.size, mode="full")
    max_lag = int((max_lag_sec * sr) / FRAME)
    mask = np.abs(lags) <= max_lag
    if not mask.any():
        return 0
    corr_masked = np.where(mask, corr, -np.inf)
    best_lag = int(lags[int(np.argmax(corr_masked))])
    return best_lag * FRAME  # 正 = 歌が遅れ


def _align(
    backing: np.ndarray, voice: np.ndarray, manual_offset_ms: float = 0.0, sr: int = SR
):
    """歌と伴奏を整列。頭を無音で埋めてそろえるので音は切らない。"""
    lag = _find_lag_samples(backing, voice, sr) + int(manual_offset_ms / 1000 * sr)

    if lag > 0:  # 歌が遅れ → 伴奏を遅らせる
        backing = np.concatenate([np.zeros(lag, dtype=np.float32), backing])
    elif lag < 0:  # 歌が早い → 歌を遅らせる
        voice = np.concatenate([np.zeros(-lag, dtype=np.float32), voice])

    n = max(backing.size, voice.size)
    b = np.zeros(n, dtype=np.float32)
    v = np.zeros(n, dtype=np.float32)
    b[: backing.size] = backing
    v[: voice.size] = voice
    return b, v, round(lag / sr * 1000.0, 1)


# ---------- ④ 歌声の音づくり ----------
def _process_vocal_tone(vocal: np.ndarray, sr: int = SR) -> np.ndarray:
    try:
        from pedalboard import Compressor, HighpassFilter, HighShelfFilter, Pedalboard

        board = Pedalboard(
            [
                HighpassFilter(cutoff_frequency_hz=90.0),
                Compressor(
                    threshold_db=-20.0, ratio=3.0, attack_ms=8.0, release_ms=180.0
                ),
                HighShelfFilter(cutoff_frequency_hz=6000.0, gain_db=2.5),
            ]
        )
        return np.asarray(board(vocal, sr), dtype=np.float32)
    except Exception as e:  # noqa: BLE001
        print(f"[warn] pedalboard 処理をスキップ: {e}")
        return vocal


# ---------- ⑥ マスター ----------
def _master_limit(mix: np.ndarray, sr: int = SR) -> np.ndarray:
    try:
        from pedalboard import Limiter, Pedalboard

        board = Pedalboard([Limiter(threshold_db=-1.0, release_ms=100.0)])
        mix = np.asarray(board(mix, sr), dtype=np.float32)
    except Exception as e:  # noqa: BLE001
        print(f"[warn] リミッターをスキップ: {e}")
    mix = _peak_normalize(mix, -1.0)
    return np.clip(mix, -1.0, 1.0).astype(np.float32)


# ---------- メイン ----------
def mix_vocal_and_backing(
    vocal_path: str,
    backing_path: str,
    out_path: str,
    vocal_lead_db: float = 3.0,
    manual_offset_ms: float = 0.0,
) -> dict:
    """歌声と伴奏を加工・整列・ミックスして WAV に書き出す。"""
    vocal = _load_mono(vocal_path)
    backing = _load_mono(backing_path)

    vocal = _denoise_vocal(vocal)
    backing, vocal, corrected_ms = _align(backing, vocal, manual_offset_ms)
    vocal = _process_vocal_tone(vocal)

    # 音量バランス：歌をピーク-3dBFS、伴奏を lead 分下げる
    vocal = _peak_normalize(vocal, -3.0)
    v_rms = _rms(vocal)
    b_rms = _rms(backing)
    target_b = v_rms / _db_to_gain(vocal_lead_db)
    backing = (backing * (target_b / (b_rms + EPS))).astype(np.float32)

    n = max(vocal.size, backing.size)
    mix = np.zeros(n, dtype=np.float32)
    mix[: vocal.size] += vocal
    mix[: backing.size] += backing
    mix = _master_limit(mix)

    sf.write(out_path, mix, SR, subtype="PCM_16")
    return {
        "output_path": out_path,
        "corrected_ms": corrected_ms,
        "duration_sec": round(mix.size / SR, 2),
        "sample_rate": SR,
    }
