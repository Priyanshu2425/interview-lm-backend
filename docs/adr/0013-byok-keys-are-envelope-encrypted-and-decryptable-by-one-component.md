# BYOK keys are envelope-encrypted and decryptable by one component

Each **BYOK** OpenRouter key is encrypted under its own data key; the data keys
are wrapped by a key-encryption key held in a managed KMS. Only the *Metered
Model Client* holds permission to unwrap. Plaintext exists in that process and
nowhere else: never logged, never in a `call_record`, never returned across an
API boundary.

## Why

ADR-0008 settled that custody is unavoidable — the **Judge** runs server-side,
so a key we cannot read cannot grade — and chose OpenRouter keys precisely to
bound what custody costs. This decision finishes that argument by bounding the
blast radius of the custody itself.

**A single application-level secret is the failure this avoids.** With one
symmetric key in configuration, any config leak, any log of the environment, any
backup of the deployment decrypts the entire table at once. Envelope encryption
makes the database dump useless without KMS access, and makes KMS access
auditable per unwrap.

## Why one component

SPEC-0005 already funnels every provider call through the Metered Model Client
so an unmetered call is impossible rather than discouraged. Attaching decrypt
permission to the same chokepoint means "who can read Candidate keys" has one
answer, enforced by IAM rather than by code review. Every other service —
including the MCP server and anything Candidate-facing — runs without it.

## Rotation and revocation

Rotating the KEK re-wraps data keys and never touches ciphertext, so rotation is
routine rather than a migration. Revocation is a status change plus deletion of
the ciphertext; the `key_fingerprint` survives so the Candidate can still see
which key was removed, and history stays readable.

## Consequence

A key cannot be recovered for support purposes, by anyone. That is intended: the
recovery path is for the Candidate to issue a new OpenRouter key, which costs
them a minute and costs us no custody we would rather not have.
