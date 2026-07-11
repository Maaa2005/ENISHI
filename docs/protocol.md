# TwinLink Protocol 0.1

エージェント間の構造化メッセージ仕様。正は [twinlink.md §25](../twinlink.md)。

Phase 4で実装予定。メッセージ共通形式・`message_type`（REQUEST / PROPOSE /
COUNTER / ACCEPT / REJECT / REQUEST_APPROVAL / APPROVAL_RESULT / EXECUTE /
RECEIPT / ERROR）・delta方式の差分交換を `packages/protocol/schemas/` に
JSON Schemaとして定義する。
