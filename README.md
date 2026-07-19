# Studio Rocky – かんたん録音サーバー（超軽量 / Flask）

イヤホンを外し、スピーカーの伴奏を聴きながら歌い、**マイクで「伴奏＋歌声」を1つの音声として一括録音**するだけのシンプルなWebアプリです。

- 2つの音を後で合成しないので、**音ズレは物理的に起こりません**。
- サーバーは「録音を保存」「保存した録音を返す」だけの**超軽量API**（重い音声処理は一切なし）。

## ファイル構成
| ファイル | 役割 |
|---|---|
| `app.py` | Flaskの軽量バックエンド（`/` ページ表示、`/upload` 保存、`/recordings/<name>` 再生） |
| `templates/index.html` | 録音・再生のフロント（MediaRecorderで一括録音） |
| `requirements.txt` | Flask と gunicorn だけ |
| `Dockerfile` | python-slim + Flask（ffmpeg不要・軽量） |
| `render.yaml` | Render の設定 |

## 使い方
1. Renderの公開URL（例 `https://studio-rocky-app.onrender.com`）をスマホで開く
2. イヤホンを**外す**
3. 「① 伴奏を選ぶ」で伴奏音源を選ぶ（無しでもOK）
4. 赤ボタンで録音 → スピーカーの伴奏を聴きながら歌う → もう一度押して停止
5. その場で再生・ダウンロードできる

## ローカルで動かす（任意）
```bash
pip install -r requirements.txt
python app.py           # http://localhost:8000
```

## Render へのデプロイ
GitHubリポジトリを更新すると、Renderが自動で再デプロイします（Docker・無料枠）。
起動コマンド: `gunicorn app:app --bind 0.0.0.0:$PORT`

## 注意
- Render無料枠の保存領域は**一時的**（再起動で消える）ため、大切な録音は端末に**ダウンロード**してください。
- 手元での再生・ダウンロードはサーバーに関係なく動きます（保存は「おまけ」）。
