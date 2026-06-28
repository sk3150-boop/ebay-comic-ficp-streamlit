# Render公開手順

この手順は、漫画CSV補完StreamlitアプリをRenderで公開するためのものです。

## 1. GitHubへリポジトリを作る

1. GitHubで新しいリポジトリを作成する。
2. このフォルダをそのリポジトリへpushする。
3. APIキー、パスワード、CSV、PDF、ログファイルはpushしない。

## 2. RenderでBlueprintを作る

1. Renderにログインする。
2. New から Blueprint を選ぶ。
3. GitHubリポジトリを選択する。
4. `render.yaml` が読み込まれることを確認する。
5. Web Service と PostgreSQL database が作成されることを確認する。

## 3. 環境変数

`render.yaml` で以下を設定する。

```text
COMIC_FICP_PUBLIC_MODE=1
COMIC_FICP_DATABASE_URL=<Render PostgreSQLの接続URL>
COMIC_FICP_KEY_ENCRYPTION_SECRET=<Render側で自動生成>
```

`COMIC_FICP_KEY_ENCRYPTION_SECRET` はAPIキー暗号化用です。外部に公開しないでください。

## 4. 公開後の確認

公開URLで以下を確認する。

1. 未ログインではCSV画面に入れない。
2. 新規登録できる。
3. ログインできる。
4. Gemini/OpenAI APIキーを保存できる。
5. 保存済みキーが画面に平文表示されない。
6. CSVを読み込み、1件処理できる。
7. CSVをダウンロードできる。
8. 別ユーザーでは保存済みキーやCSV処理結果が見えない。

## 注意

- RenderのWeb ServiceやPostgreSQLはプランにより課金される場合があります。
- API補完の料金は、利用者が保存したOpenAI/Gemini APIキー側に発生します。
- パスワードリセットやメール認証はv1では未実装です。
