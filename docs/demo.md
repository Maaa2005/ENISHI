# TwinLink 2ノード＋Relayデモ

## 起動

3つのターミナルで起動する。

```bash
./scripts/run_demo_relay.sh
./scripts/run_demo_user_a.sh
./scripts/run_demo_user_b.sh
```

一括起動する場合:

```bash
./scripts/run_demo_all.sh
```

起動先:

| process | URL | token | data dir |
|---|---|---|---|
| Relay | `http://127.0.0.1:8870` | `relay-token-a` / `relay-token-b` | `.tmp/demo-relay` |
| User A | `http://127.0.0.1:8871` | `demo-token-a` | `.tmp/demo-user-a` |
| User B | `http://127.0.0.1:8872` | `demo-token-b` | `.tmp/demo-user-b` |

各Local Coreは独立SQLite、独立鍵、独立データディレクトリを使う。Relayは `.tmp/demo-user-a` と `.tmp/demo-user-b` の鍵から実Agent IDを読み、`RELAY_NODE_TOKENS` を自動設定する。

## ペアリング

別ターミナルでそれぞれの公開鍵を確認する。

```bash
curl -s -H "Authorization: Bearer demo-token-a" \
  http://127.0.0.1:8871/v1/node/identity

curl -s -H "Authorization: Bearer demo-token-b" \
  http://127.0.0.1:8872/v1/node/identity
```

User AにUser Bを登録し、User BにUser Aを登録する。`agent_id` と `public_key` は上の結果を入れる。

```bash
curl -s -X POST -H "Authorization: Bearer demo-token-a" -H "Content-Type: application/json" \
  -d '{"agent_id":"<B_AGENT_ID>","display_name":"Demo User B","public_key":"<B_PUBLIC_KEY>"}' \
  http://127.0.0.1:8871/v1/peers
curl -s -X POST -H "Authorization: Bearer demo-token-a" \
  http://127.0.0.1:8871/v1/peers/<B_AGENT_ID>/trust

curl -s -X POST -H "Authorization: Bearer demo-token-b" -H "Content-Type: application/json" \
  -d '{"agent_id":"<A_AGENT_ID>","display_name":"Demo User A","public_key":"<A_PUBLIC_KEY>"}' \
  http://127.0.0.1:8872/v1/peers
curl -s -X POST -H "Authorization: Bearer demo-token-b" \
  http://127.0.0.1:8872/v1/peers/<A_AGENT_ID>/trust
```

## 公開設定

相手ごとのSelective Disclosureを設定する。

```bash
curl -s -X PUT -H "Authorization: Bearer demo-token-a" -H "Content-Type: application/json" \
  -d '{"allowed_memory_types":["schedule","preference"],"max_sensitivity":"internal","share_schedule":true,"share_skills":false,"extra":{}}' \
  http://127.0.0.1:8871/v1/peers/<B_AGENT_ID>/disclosure

curl -s -X PUT -H "Authorization: Bearer demo-token-b" -H "Content-Type: application/json" \
  -d '{"allowed_memory_types":["schedule","preference"],"max_sensitivity":"internal","share_schedule":true,"share_skills":false,"extra":{}}' \
  http://127.0.0.1:8872/v1/peers/<A_AGENT_ID>/disclosure
```

## デスクトップ画面で確認

DesktopをUser Aへ接続する場合:

```bash
cd apps/desktop
TWINLINK_LOCAL_PORT=8871 TWINLINK_LOCAL_TOKEN=demo-token-a npm run dev
```

画面で確認する流れ:

1. `Peers` でピア状態、フィンガープリント、公開設定を確認する。
2. `交渉` で `meeting.schedule` または `task.request` を実行し、タイムラインのJSONメッセージを見る。
3. `合意` でAgreementを確認し、`fulfilled` または `cancelled` へ変更する。
4. `承認` で `task.request` の `waiting_approval` を承認または拒否する。
5. `メトリクス` でメール方式との比較実験を実行し、テンプレート、往復数、delta有無、総トークン、メッセージ数、LLM呼び出し回数、削減率を確認する。

## Relay経由の日程調整

User Aでユーザーとクローンを作成してactiveにする。

```bash
curl -s -X POST -H "Authorization: Bearer demo-token-a" -H "Content-Type: application/json" \
  -d '{"display_name":"User A"}' http://127.0.0.1:8871/v1/users
curl -s -X POST -H "Authorization: Bearer demo-token-a" -H "Content-Type: application/json" \
  -d '{"purpose":"交渉","provider_type":"mock"}' http://127.0.0.1:8871/v1/clones/<USER_A_ID>/ensure
curl -s -X POST -H "Authorization: Bearer demo-token-a" \
  http://127.0.0.1:8871/v1/clones/<CLONE_A_ID>/activate
```

User Bも同様にユーザーとactiveクローンを作る。

User AからRelayへ `REQUEST` / `PROPOSE` を送る。

```bash
curl -s -X POST -H "Authorization: Bearer demo-token-a" -H "Content-Type: application/json" \
  -d '{"user_id":"<USER_A_ID>","peer_agent_id":"<B_AGENT_ID>","topic":"AIエージェントの企画","duration_minutes":30,"date_range":{"start":"2026-07-13","end":"2026-07-17"},"preferred_time_ranges":[{"start":"13:00","end":"18:00"}]}' \
  http://127.0.0.1:8871/v1/remote-negotiations
```

User Bで受信箱を処理し、必要ならUser Aでも処理する。

```bash
curl -s -X POST -H "Authorization: Bearer demo-token-b" \
  http://127.0.0.1:8872/v1/relay/inbox/process
curl -s -X POST -H "Authorization: Bearer demo-token-a" \
  http://127.0.0.1:8871/v1/relay/inbox/process
```

合意は双方の `/v1/agreements`、JSONタイムラインは `/v1/negotiations/{session_id}/messages`、トークン比較は画面の `メトリクス` または `/v1/metrics/experiments` で確認する。
