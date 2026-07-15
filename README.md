# Studio Rocky – AI ミックス処理サーバー

歌声と伴奏（インスト）の2つの音源を受け取り、**ノイズ除去・音ズレ自動補正・コンプ／リミッター**でプロ品質にミックスして返す Python サーバー（FastAPI）です。

- スマホアプリからは `POST /api/mix-audio` に2ファイルを送るだけ
- 返ってくるのは、完成した1つの音声ファイル（wav または mp3）

---

## 何が起きるの？（処理の中身）

| 順番 | 処理 | 使うもの |
|---|---|---|
| ① | 歌声のノイズ除去 | `noisereduce`（AIベース） |
| ② | **音ズレを自動で検出・補正** | `librosa` + `scipy`（相互相関） |
| ③ | 歌声を整える（ハイパス→コンプ→高域） | `pedalboard`（Spotify製） |
| ④ | 音量バランス最適化（歌を前に） | RMS基準の自動調整 |
| ⑤ | ミックス＆**0dBを超えない**リミッター | `pedalboard` |

> 今いちばん困っていた「歌と伴奏のズレ」は、②で**2音源の“音の立ち上がり”を相互相関にかけ、ミリ秒単位で自動整列**して解決します。

---

## セットアップ（初心者向け・順番にやればOK）

### 1. Python を用意
Python **3.10 以上**を入れてください（`python --version` で確認）。

### 2. ffmpeg を入れる（mp3 / m4a を扱うのに必須）
- **Windows**: [https://www.gyan.dev/ffmpeg/builds/](https://www.gyan.dev/ffmpeg/builds/) から入手し、`ffmpeg.exe` のあるフォルダを環境変数 PATH に追加
  （または PowerShell で `winget install ffmpeg`）
- **Mac**: `brew install ffmpeg`
- 確認: `ffmpeg -version` が表示されればOK

### 3. このフォルダで仮想環境を作って依存を入れる
```bash
# このフォルダ（audio-mix-server）で実行
python -m venv venv

# 仮想環境を有効化
#   Windows(PowerShell):
venv\Scripts\Activate.ps1
#   Mac/Linux:
source venv/bin/activate

# ライブラリをインストール
pip install -r requirements.txt
```
> `pedalboard` や `librosa` は初回だけ時間がかかります。ゆっくり待ってください。

### 4. サーバーを起動
```bash
uvicorn main:app --host 0.0.0.0 --port 8000
```
起動したら、ブラウザで `http://localhost:8000/` を開き、`{"status":"ok",...}` が出れば成功です。

---

## 使い方（動作テスト）

### curl で試す
```bash
curl -X POST http://localhost:8000/api/mix-audio \
  -F "vocal=@歌声.wav" \
  -F "backing=@伴奏.mp3" \
  -o 完成ミックス.wav
```
`完成ミックス.wav` が出来上がります。補正したズレ量はレスポンスヘッダ `X-Corrected-Ms` に入っています。

### 付属のテストスクリプトで試す
```bash
python test_client.py 歌声.wav 伴奏.mp3
```

---

## API 仕様

### `POST /api/mix-audio`
**送るもの（multipart/form-data）**

| 名前 | 必須 | 内容 |
|---|---|---|
| `vocal` | ✅ | 歌声ファイル（wav/mp3/m4a/aac/ogg/flac） |
| `backing` | ✅ | 伴奏ファイル（同上） |
| `output_format` | 任意 | `wav`（既定）または `mp3` |
| `vocal_lead_db` | 任意 | 歌を伴奏より何dB前に出すか（既定 `3.0`） |

**返ってくるもの**
- 成功：ミックス済み音声ファイル（本文）＋ヘッダ `X-Corrected-Ms`（補正ms）
- 失敗：JSON `{"detail": "エラー内容"}`（400/413/422/500）

---

## スマホアプリ側の作り方（重要なメモ）

このサーバーは「**歌声だけの音源**」と「**伴奏だけの音源**」の2つを別々に受け取る前提です。

- **伴奏**：アプリが再生している音源ファイル（内蔵伴奏なら録音時に別トラックで書き出す／ファイル伴奏ならその元ファイル）
- **歌声**：録音した声だけ（伴奏を混ぜずに録る）

こうして2つを別々に送れば、サーバーがズレを補正して混ぜるので、
ブラウザ側でタイミングをピッタリ合わせる必要がなくなります。

---

## デプロイ（本番公開）について
Python が動くサーバーが必要です（エックスサーバー等の一般的な共有レンタルサーバーでは動きません）。
- 手軽: **Render / Railway / Fly.io** などのPaaS、または **VPS**
- 本番起動例: `uvicorn main:app --host 0.0.0.0 --port $PORT`
- 大きなファイル・同時アクセスが増えたら、処理を非同期ジョブ化（Celery等）する拡張も可能です。

## 困ったとき
- `ffmpeg not found` 系エラー → 手順2をやり直し（PATH確認）
- `pip install` でエラー → Python を 3.10〜3.12 に、`pip install --upgrade pip` してから再実行
- mp3出力で失敗 → まずは `output_format=wav`（既定）で試す
