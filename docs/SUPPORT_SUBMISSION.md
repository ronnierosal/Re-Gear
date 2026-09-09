# Secure support-bundle submission design

Support submission is not enabled. Re-Gear currently previews, copies, and saves a
bundle locally. This document defines the later security boundary without
embedding a server address, credential, or upload token.

## Separate approval

Logging consent, local save consent, and upload consent are independent. A
future **Submit** action must issue a new five-minute, single-use approval bound
to the exact UTF-8 bytes the player already reviewed. Consumption returns only:

- exact body bytes
- `application/json`
- byte length, at most 256 KiB
- SHA-256 checksum

No endpoint, path, filename, account identity, R2 key, bearer token, or cloud
credential is accepted from the frontend or stored in this approval object.

## Worker contract

The future deployment should use one backend-owned HTTPS endpoint:

```text
Re-Gear -> HTTPS -> narrowly scoped Cloudflare Worker -> private R2 bucket
```

The Worker must:

- accept only `POST` with exact `application/json`
- enforce the encoded size limit before parsing
- validate bundle schema and checksum
- reject unknown top-level fields where the protocol specifies a closed shape
- rate-limit and apply abuse controls before R2 writes
- generate the R2 object key and non-guessable report ID server-side
- never accept a client filesystem/object path
- store uploads in a private bucket with a roughly 30-day lifecycle policy
- have only the minimum R2 write permission needed for that bucket/prefix
- never execute, unpack, render, or serve submitted content as active content
- return only `{ "ok": true, "report_id": "Re-Gear-..." }`
- record an auditable categorical outcome without copying bundle contents into
  general Worker logs

The client parser accepts only the exact success response and a bounded
`Re-Gear-[A-Z0-9]` report ID. Redirect URLs, object URLs, extra fields, and
client-chosen IDs are rejected.

## Dormant client adapter

A fixed-configuration HTTPS adapter now implements the client side of this
boundary. It accepts only a public DNS HTTPS URL on port 443 with a bounded
path and no credentials, query, fragment, or IP-literal host. It sends the
exact approved bytes once with their size and SHA-256, uses the platform TLS
verifier, follows no redirects, limits the response to 1 KiB, requires exact
`application/json`, and reduces transport failures to categorical codes that
do not expose response bodies or endpoint details.

The endpoint is construction-time backend configuration, never part of the
approval or a frontend parameter. The production plugin does not construct
this adapter.

## Current boundary

The approval store, checksum/size revalidation, strict response parser, fixed
HTTPS adapter, and unimplemented fixed-configuration port are unit tested.
There is no configured endpoint, Worker project, R2 bucket, DNS, credential,
public RPC, or UI action.
Creating cloud resources and choosing production abuse/rate-limit settings
require a separate deployment decision and account authorization.
