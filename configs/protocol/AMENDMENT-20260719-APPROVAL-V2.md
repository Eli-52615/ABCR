# ABCR Approval V2

Production token algorithm: Ed25519. Required signed claims are `version`, `alg`, `token_id`, `scope`, `aud`, `deployment_id`, `protocol_ref`, `request_id`, `batch_id`, `envelope_sha256`, `decision`, `expires_at`, `nonce`, and `key_fingerprint`.

The human-domain process alone reads the private key. Operator processes receive a self-contained approval request bundle and verify with the root-owned public key. Mutation, expiry, environment replay and second consumption fail closed.
