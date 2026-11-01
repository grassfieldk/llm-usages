# LLM Usages

Windows の通知領域から Codex と Claude のサブスクリプション使用状況を確認する常駐アプリ

アイコンをクリックすると残り割合とリセットまでの時間を表示します。バーは残り割合を表し、リセット時刻は時間表示にマウスを重ねると確認できます。アイコンへのマウスホバーでも残り割合を確認できます。自動更新は初期設定で 5 分ごとです。取得に失敗した場合は前回取得した値と取得時刻を表示します

## 起動

PowerShell で mise が有効な状態で実行します

```powershell
# 初回セットアップ
mise run setup
# 通知領域に起動
mise run start
```

セットアップ後は `start.vbs` のダブルクリックでも起動できます。設定で自動更新間隔と Windows 起動時の自動起動を変更できます

## ログイン

Codex は Codex アプリまたは CLI のログイン情報を使います。アプリの「ログイン」から認証し、完了後に「更新」を押してください

Claude はアプリ専用にログインします。「ログイン」を押すとブラウザで Claude のログイン画面が開き、許可すると自動で取得を始めます。Claude Code とは別のログイン情報を持つため、Claude Code のログイン状態には影響しません。ログイン情報は Windows の資格情報マネージャーに保存し、期限が切れると自動で更新します

## データ取得

- Codex: 公式 app-server の `account/rateLimits/read` を使用
- Claude: OAuth の使用状況エンドポイントを使用。公開 API として保証されていないため、サービス側の変更で取得できなくなる場合があります
- リセット時刻: Windows のローカル時刻で表示

使用状況の取得だけを行い、モデルへのメッセージ送信は行いません

```powershell
# 実際の取得結果を確認
mise run check
```

参照: [Codex App Server](https://learn.chatgpt.com/docs/app-server)、[Claude の使用状況の実装例](https://github.com/steipete/CodexBar/blob/main/docs/claude.md)
