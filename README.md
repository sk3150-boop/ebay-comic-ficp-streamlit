# eBay Manga CSV FICP Assistant

eBay出品用CSVに対して、メルカリ等の公開商品情報を参照しながら漫画セットのItem Specifics補完、冊数判定、FedEx FICP送料計算、送料無料価格転嫁、CSV出力を行うStreamlitアプリです。

## ローカル起動

```powershell
python -m pip install -r requirements-streamlit.txt
python -m playwright install chromium
streamlit run comic_ficp_streamlit_app.py
```

Windowsローカル版では、AI APIキーを保存した場合のみ、Windowsユーザー暗号化領域を使って `%APPDATA%\ComicFicpStreamlit\api_keys.json` に保存します。

## 公開版の起動

公開版ではログイン必須になり、利用者ごとにOpenAI/Gemini APIキーをサーバーDBへ暗号化保存します。CSVや処理結果はStreamlitセッション内だけで扱い、ローカルキャッシュファイルには保存しません。

必須環境変数:

```text
COMIC_FICP_PUBLIC_MODE=1
COMIC_FICP_DATABASE_URL=postgresql://...
COMIC_FICP_KEY_ENCRYPTION_SECRET=<十分に長いランダム文字列>
```

Dockerで起動する場合:

```powershell
docker build -t comic-ficp-streamlit .
docker run --rm -p 8501:8501 `
  -e COMIC_FICP_PUBLIC_MODE=1 `
  -e COMIC_FICP_DATABASE_URL="postgresql://..." `
  -e COMIC_FICP_KEY_ENCRYPTION_SECRET="change-this-secret" `
  comic-ficp-streamlit
```

Renderへ置く場合は `render.yaml` を使い、PostgreSQL databaseとWeb Serviceを作成します。

## セキュリティ方針

- 公開版は未ログインではCSVアップロード画面へ入れません。
- パスワードはPBKDF2-SHA256でハッシュ化保存します。
- AI APIキーは `COMIC_FICP_KEY_ENCRYPTION_SECRET` から作った暗号鍵で暗号化保存します。
- APIキー、パスワード、DBパスワードはCSV、診断UI、CodexHubログへ出さない方針です。
- AI API料金は、保存した利用者本人のAPIキー側に発生します。

## テスト

```powershell
python -m py_compile comic_ficp_streamlit_app.py tests\test_comic_ficp_logic.py
python -m unittest tests.test_comic_ficp_logic
```
