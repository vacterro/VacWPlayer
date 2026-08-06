🇪🇪 [Eesti](README.ee.md) | 🇷🇺 [Русский](README.ru.md) | 🇺🇸 [English](README.md) | 👴 [Дед-Мод](README.ded.md) | 🇯🇵 **日本語**

# WildRiftAssistant

**v0.2.1** — [変更履歴](CHANGELOG.md)

Wild Rift ツールキット全体を覆うヴィンテージ風GUI：ペダルコンボ、チャンピオン別ローテーション、死亡時の自動最小化、試合後の自動継続 — 手作業でスクリプトを編集せずに使える「スーパーAHK」。

## 機能

- **メインタブ** — グローバル入力トグル（マウスリマップ、スペース連打、AFK対策、停止キー、手動エイムの一時停止、対象exe）とGeneralモードのカスタムコンボ一覧：追加、削除、全消去、キー押下でのトリガー登録、レガシーデフォルトへのリセット。
- **Ryzeタブ** — Wave / Jungle / PVP のローテーションを実コンボでプリロード、起動時に即反映。
- **Xin Zhaoタブ** — 現行メタガイド準拠の E→W→Q エンゲージコンボ。
- **Death Watch / Auto Continue タブ** — 既存エンジン `deathwatch.py` / `autocontinue.py` を操作（ドライラントグル、ライブステータス）。`--replace` でクリーンに引き継ぐ。
- **チャンピオンモード**（General / Ryze / Xin ラジオ）で有効なコンボセットは常に1つ。F13–F15 がヒーロー間で衝突しない。
- **ステップ毎の遅延** — `キー:ms` 構文、例：`q,e:120,{Space}:200`。
- **トレイアイコン** — X でトレイに格納、エンジンは稼働継続。Quit で全停止。
- **Wiki** — アーキテクチャ、設定リファレンス、タブガイド: `docs/wiki/`。

## 必要環境

- Windows、Python 3.11、プロジェクトvenv（`../venv`）。
- AutoHotkey v1: アプリの隣に `AutoHotkeyU64.exe` があればそれを、なければ標準インストール先（`C:\Program Files\AutoHotkey\`）を使用。
- `pip install -r requirements.txt`。

## 起動

**`WildRiftAssistant.vbs`** をダブルクリック（コンソール非表示で静かに起動）。エラー表示が必要なら **`WildRiftAssistant.bat`** を手動実行（`--check` 診断対応）。どちらもvenvを自動検出。
手動の場合は:

```
..\venv\Scripts\pythonw.exe main.pyw
```

Ryze アシストは自動起動。タブを編集してチャンピオンを選び、**Apply & Start** を押すだけ。

## テスト

```
python -m pytest tests/ -v
```

pytest が必要（`pip install pytest` または `pip install -r requirements.txt`）。
テストは非GUIモジュールのインポートと全 .py ファイルのコンパイルを検証。

## 仕組み

GUI自身はキーをフックしない — `config.json` から `ahk_generator.py` 経由で `wr_runtime.ahk` を生成し、AutoHotkey を起動するだけ（BlueStacks に必要な Event モード）。追跡・強制終了するのは自分で起動したランタイムのみ（PID管理）。他の AHK スクリプトには手を出さない。旧手書きの `wr.ahk` は起動時に自動で退役。

設定ファイルは3つ、役割はそれぞれ1つずつ：`config.json`（コンボ、モード、トグル）、`deathwatch_config.json`（死亡検知）、`autocontinue_config.json`（試合後ボタン）。`wr_runtime.ahk` は生成物 — 手編集禁止。

## コンボ構文

カンマ区切りのキー列。`{Space}`、`f`、英字。能力キー q/w/e/r は「Shift-cast」がオフでなければシフトキャスト（自キャスト）。キーに `:ms` を付けるとそのステップ固有の遅延。それ以外はコンボ間隔が適用。トリガーペダルを押しっぱなしでループ。

<!-- source-digest: README.md sha256:64a14fd91deee05c -->
