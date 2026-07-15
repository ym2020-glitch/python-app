"""
test_client.py
--------------
サーバーの動作確認用スクリプト。
使い方:
    python test_client.py 歌声.wav 伴奏.mp3
    python test_client.py 歌声.wav 伴奏.mp3 --format mp3 --url http://localhost:8000

成功すると同じフォルダに mixed_result.<形式> が作られます。
"""

import argparse
import sys

import requests  # pip install requests （テスト用。サーバー本体には不要）


def main() -> int:
    parser = argparse.ArgumentParser(description="Studio Rocky Mix API テスト")
    parser.add_argument("vocal", help="歌声ファイル")
    parser.add_argument("backing", help="伴奏ファイル")
    parser.add_argument("--format", default="wav", choices=["wav", "mp3"])
    parser.add_argument("--lead", type=float, default=3.0, help="歌を前に出す量(dB)")
    parser.add_argument("--url", default="http://localhost:8000")
    args = parser.parse_args()

    endpoint = f"{args.url}/api/mix-audio"
    params = {"output_format": args.format, "vocal_lead_db": args.lead}

    print(f"送信中… {endpoint}")
    try:
        with open(args.vocal, "rb") as fv, open(args.backing, "rb") as fb:
            files = {
                "vocal": (args.vocal, fv),
                "backing": (args.backing, fb),
            }
            resp = requests.post(endpoint, params=params, files=files, timeout=300)
    except FileNotFoundError as e:
        print(f"ファイルが見つかりません: {e}")
        return 1
    except requests.RequestException as e:
        print(f"通信エラー: {e}")
        return 1

    if resp.status_code != 200:
        print(f"失敗 ({resp.status_code}): {resp.text}")
        return 1

    out = f"mixed_result.{args.format}"
    with open(out, "wb") as f:
        f.write(resp.content)
    corrected = resp.headers.get("X-Corrected-Ms", "?")
    print(f"成功！ {out} を書き出しました（補正: {corrected} ms）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
