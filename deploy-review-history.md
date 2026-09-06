# 漫画FICP 精査履歴版の公開反映・復旧

対象は既存の ConoHa VPS `160.251.211.136`、公開URLは <https://160-251-211-136.nip.io/>。
作業ディレクトリは `/opt/comic-ficp`、Composeは `docker-compose.vps.yml`、サービスは `app` / `db`。
この手順は履歴版の反映用であり、ホスティング・認証方式の変更は行わない。

## 1. 反映前の保全

- 処理中のCSVがないことを確認する。アプリ再作成でブラウザ接続・未保存セッションは切れるため、必要なCSVを先に保存する。
- 公開中のコミット、アプリのイメージID、Compose設定、DBボリューム、ポート割当を確認し、秘密値を含まない情報だけを作業ログに残す。
- `POSTGRES_PASSWORD` と `COMIC_FICP_KEY_ENCRYPTION_SECRET` は、**現在稼働中の値を維持する**。暗号化秘密値の再生成は保存済みAPIキーを復号できなくする。プロジェクトに `.env` が存在するとは限らないため、削除・再作成の前に既存コンテナから安全に確保する。
- 秘密値を含む環境のバックアップは、リポジトリ外のroot専用ディレクトリ（0700）・ファイル（0600）だけに保存する。画面・ログ・Git・CodexHubへ環境変数や `docker inspect` 全文を出力しない。
- 2026-09-07の事前確認ではアプリは `0.0.0.0:8501` / `[::]:8501`、DBは外部ポート公開なし。反映直前の実設定を正とし、この更新で公開範囲を変更しない。

以下はVPS上のBashで実行する。DBと前イメージを保全し、新イメージの検証が終わるまで旧イメージを削除しない。

```bash
set -eu
cd /opt/comic-ficp
umask 077
stamp=$(date -u +%Y%m%dT%H%M%SZ)
backup_dir="/root/comic-ficp-backups/review-$stamp"
mkdir -p "$backup_dir"
chmod 700 "$backup_dir"
git rev-parse HEAD > "$backup_dir/previous-commit.txt"
cp docker-compose.vps.yml "$backup_dir/previous-compose.yml"
previous_image=$(docker inspect comic-ficp-app-1 --format '{{.Image}}')
rollback_tag="comic-ficp-app:before-review-$stamp"
docker image tag "$previous_image" "$rollback_tag"
printf '%s\n' "$rollback_tag" > "$backup_dir/rollback-image.txt"
docker exec comic-ficp-db-1 pg_dump -U comic_ficp -d comic_ficp -Fc > "$backup_dir/comic_ficp.dump"
test -s "$backup_dir/comic_ficp.dump"
docker exec -i comic-ficp-db-1 pg_restore --list < "$backup_dir/comic_ficp.dump" > "$backup_dir/dump-contents.txt"
```

必要なら旧イメージも `docker image save` でバックアップ先へ保存する。環境バックアップとDBダンプは同じ復旧単位で保全し、秘密値を取り扱える場所に限って保管する。

## 2. アプリだけを更新

1. 公開対象コミットのテスト成功を確認し、サーバーの既存変更を点検してから、そのコミットへfast-forwardで更新する。無関係な変更を上書きする `git reset --hard` は使わない。
2. 保存しておいた現在の環境値をComposeへ供給する。公開モード、ログイン不要設定、共通workspace名、DB接続先、暗号化秘密値、ポート割当を維持する。環境の内容は表示しない。
3. 設定検証・ビルド後、`app` だけを再作成する。`db` の再作成、ボリューム削除、`docker compose down -v`、イメージ一括削除は行わない。

```bash
docker compose -p comic-ficp -f docker-compose.vps.yml config --quiet
docker compose -p comic-ficp -f docker-compose.vps.yml build app
docker compose -p comic-ficp -f docker-compose.vps.yml up -d --no-deps --no-build app
curl --fail --silent --show-error http://127.0.0.1:8501/_stcore/health
curl --fail --silent --show-error https://160-251-211-136.nip.io/_stcore/health
```

初回アクセス時に `comic_review_runs` / `comic_review_items` / `comic_review_images` / `comic_review_revisions` / `comic_review_exports` が追加される。既存のアカウント・APIキー・タイトル手動補正テーブルを置換しない。初回の履歴は空で正常であり、導入前に失われたセッションは復元されない。

ヘルス応答だけで完了にしない。公開画面でログイン不要の起動、CSV投入、5件試行、判定一覧と詳細、試行CSV、履歴再読込、履歴CSVの内容を確認する。履歴閲覧だけで有料APIや商品元取得が走らないこと、300g / 0.8kg / 45% / 5件の既定値、PC・スマートフォン表示も確認する。専用の検証データは他の履歴と区別する。

## 3. 問題がある場合は前イメージへ戻す

通常のロールバックは **DBをそのまま保持し、アプリだけを前イメージへ戻す**。履歴テーブルの追加は旧アプリと共存できるため、旧アプリに戻すためだけのDBリストアや履歴テーブル削除は不要。反映後に保存された履歴も保持する。

- バックアップの `rollback-image.txt` にあるタグを使う。ロールバック用Compose上書きファイルは次の内容とし、`image` に実際の保存済みタグを指定する。

```yaml
services:
  app:
    image: comic-ficp-app:before-review-REPLACE_WITH_SAVED_TIMESTAMP
    pull_policy: never
```

- 同じ秘密値・ポート割当を供給した状態で、`docker compose -p comic-ficp -f docker-compose.vps.yml -f /root/安全な場所/rollback-image.yml up -d --no-deps --no-build app` を実行する。旧イメージへ新コードをビルドし直さない。
- 内部・公開ヘルスと公開画面を再確認する。旧UIでは新履歴ページは表示されないが、DB内の履歴は残る。ソースのバージョンと稼働イメージが異なる復旧状態をログへ明記し、次回ビルド前に整合させる。
- DBリストアは、DB破損などアプリだけで復旧できない場合に限る。現在DBを別途バックアップしたうえで、反映後の履歴・設定更新が失われる対象と影響を確認してから実施する。既存DBへ無条件に `pg_restore --clean` を実行しない。

反映・復旧後は、対象コミット／稼働イメージ、検証結果、バックアップの所在、残課題をCodexHubの作業ログと漫画FICPの引き継ぎへ記録する。秘密値やDBの内容は転記しない。
