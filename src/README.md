# Application source

Phase 0-F以降のApplication本体を配置します。実装基準は次の文書です。

- [Mercari Adapter実装仕様](../docs/phase-0-f-adapter-spec.md)
- [MVP実装仕様](../docs/mvp-spec.md)

予定構成:

```text
src/
├── backend/     # Python Domain、Use case、Adapter、FastAPI
└── frontend/    # TypeScript + React + Vite
```

Phase 0のPoC固有コードは`poc/`に残し、本体からimportしません。Frontendは管理下の
`mercapi` Fork、Mercari Endpoint、DPoP、Fork固有型を直接参照しない方針です。
