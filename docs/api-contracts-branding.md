# refraq API Contracts: Site Branding

## 1. Purpose

This document defines the public read and authenticated management API for **Site Branding**, including consumer-side locale resolution, cache validators, asset handling, partial update semantics, and reset.

Related boundaries:

- Business rules: `docs/business-branding.md`.
- Console shell: `docs/business-management-console.md`.
- Errors and request IDs: `docs/conventions-errors.md`.

## 2. Transport And Authorization

Success bodies use JSON except asset byte responses and bodyless responses. Failures use RFC 9457 Problem Details from `docs/conventions-errors.md`.

`GET /branding` and `GET /branding/assets/{kind}` are public and require no Session or User PAT. All mutations accept Session or User PAT and require `branding:write`. `branding:read` controls Console Module visibility; it is not required for the public reads. Existing custom Roles do not receive either Permission automatically; `super_admin` has both by definition.

The API does not accept a locale query, does not inspect `Accept-Language`, and does not return or accept an attribution field.

## 3. Public Branding Shape

```json
{
  "brand_names": {
    "en-US": "Mingrui Data",
    "zh-CN": "Mingrui Data China"
  },
  "taglines": {
    "en-US": "Operations in context"
  },
  "primary_color": "#3569C8",
  "primary_shades": [
    "#EDF3FF",
    "#DBE7FF",
    "#B4CDFF",
    "#8BB1FF",
    "#6598FA",
    "#4D7FE3",
    "#3569C8",
    "#2953A1",
    "#1E3D79",
    "#122752"
  ],
  "show_logo": true,
  "show_brand_name_with_logo": true,
  "logo_url": "/api/branding/assets/logo?v=2f3a...",
  "favicon_url": "/api/branding/assets/favicon?v=7be1...",
  "logo_source": "user",
  "favicon_source": "seed"
}
```

| Field | Contract |
| --- | --- |
| `brand_names` | Unresolved locale-to-text map; always present; `{}` when unset |
| `taglines` | Unresolved locale-to-text map; always present; `{}` when unset |
| `primary_color` | Six-digit `#RRGGBB`, or null |
| `primary_shades` | Exactly ten six-digit `#RRGGBB` values, or null |
| `show_logo` | Boolean; defaults to `true`. Controls whether first-party surfaces paint the logo; does not clear `logo_url` |
| `show_brand_name_with_logo` | Boolean; defaults to `true` |
| `logo_url` / `favicon_url` | Same-origin browser path with checksum query, or null |
| `logo_source` / `favicon_source` | `seed` or `user` when the corresponding URL is present; null when the kind is absent. `user` means a stored operator overlay. `seed` is read-time presentation of the current packaged seed file when no overlay exists. Origin is not persisted. Not inferred from checksum. Not an authorization boundary |

The URL checksum is the SHA-256 of the bytes being served: the overlay when `source` is `user`, otherwise the current packaged seed file. Consumers treat each URL as opaque and must not substitute `logo_url` when `favicon_url` is null. Checksum equality with the current packaged seed does not mean `source` is `seed`.

### 3.1 Text Map Rules

Locale keys are supported Console UI locale codes, use BCP 47-style syntax, and are at most 35 characters. Values are trimmed, non-empty plain text. Brand names have `maxLength: 80`; taglines have `maxLength: 160`. HTML and Markdown are unsupported. A locale must be registered in both the Console locale catalog and backend supported-locale set before the API accepts it.

### 3.2 Brand Name Resolution

Given current locale `L`, site default locale `D = NEXT_PUBLIC_DEFAULT_LOCALE`, and ordered `LOCALE_CATALOG`, the consumer returns the first non-empty value from:

1. `brand_names[L]`
2. `brand_names[D]`
3. each `brand_names[locale]` in `LOCALE_CATALOG` order, excluding `L` and `D`
4. the literal `Refraq`

This algorithm is part of the API contract. All consumers, including server-rendered metadata and live client presentation, implement the same resolution.

### 3.3 Tagline Resolution

`brand_configured` is true exactly when any `brand_names` value is non-empty.

- When false, the consumer returns Refraq's localized default product-positioning tagline.
- When true, the consumer returns `taglines[L]` when non-empty, otherwise an empty tagline.

A configured site's tagline never falls back across customer locales and never falls back to Refraq copy. A primary color or asset without any brand name leaves `brand_configured` false.

## 4. `GET /branding`

Purpose: read the unresolved public branding resource for login, browser metadata, and Console presentation.

### Response: `200`

Returns §3 and:

```http
Cache-Control: public, max-age=30, stale-while-revalidate=60
ETag: "sha256-of-canonical-representation"
```

The server may retain the resource in process memory for approximately 30 seconds. The ETag is content-derived and changes whenever the public representation changes. `If-None-Match` with the current validator returns `304` with no body and the same cache headers. No `Vary` header is required because the response is locale-independent.

When no configuration row and no operator overlays exist, and product seed resolution is skipped, the response is:

```json
{
  "brand_names": {},
  "taglines": {},
  "primary_color": null,
  "primary_shades": null,
  "show_logo": true,
  "show_brand_name_with_logo": true,
  "logo_url": null,
  "favicon_url": null,
  "logo_source": null,
  "favicon_source": null
}
```

That empty-store shape is the public representation when packaged seeds are not resolved. When packaged seeds are resolved, both URLs are present and both sources are `seed` without inserting seed bytes into storage.

Read failure is `503 BRANDING_READ_FAILED`. A first-party consumer must continue rendering when this request fails or times out. It omits logo and favicon when those URLs are absent. It also omits painting the logo when `show_logo` is false, even when `logo_url` is present. It must not substitute `logo_url` when `favicon_url` is null.

## 5. `PUT /branding`

Purpose: partially replace configuration fields. Permission: `branding:write`.

### Request

```json
{
  "brand_names": {
    "en-US": "Mingrui Data"
  },
  "taglines": {},
  "primary_color": "#3569C8",
  "primary_shades": [
    "#EDF3FF",
    "#DBE7FF",
    "#B4CDFF",
    "#8BB1FF",
    "#6598FA",
    "#4D7FE3",
    "#3569C8",
    "#2953A1",
    "#1E3D79",
    "#122752"
  ],
  "show_logo": false,
  "show_brand_name_with_logo": false
}
```

Every field is optional. Unknown fields are rejected.

| Input state | Meaning |
| --- | --- |
| Field omitted | Preserve the stored field |
| `brand_names: null` or `{}` | Clear every brand name |
| `taglines: null` or `{}` | Clear every tagline |
| Locale map present | Replace the whole map; an omitted locale key is cleared |
| `primary_color: null` and `primary_shades: null` | Clear custom primary color and palette |
| `show_logo: null` | Restore default `true` |
| `show_brand_name_with_logo: null` | Restore default `true` |

Text values are trimmed before persistence. A whitespace-only value is invalid rather than silently retained as a map entry.

`primary_color` and `primary_shades` form one update pair. If either field is present, both must be present and both must be non-null or both null. The Console generates the ten shades with `@mantine/colors-generator` and is the sole product author of that derived array. The backend validates only pair presence, exact array length, and each field's hexadecimal shape; it does not generate, clamp, or compare the shades with the primary color.

### Response: `200`

Returns the current public branding shape (§3), with its new `ETag` and cache headers. A successful write invalidates the writer process's in-memory copy and writes a `site_branding` Management Audit Event.

### Errors

| Status | Problem Code | Condition |
| --- | --- | --- |
| `401` | `AUTH_UNAUTHENTICATED` | No valid Session or User PAT |
| `403` | `AUTH_FORBIDDEN` | Missing `branding:write` |
| `422` | `REQUEST_INVALID` | Unknown field or malformed JSON shape |
| `422` | `BRANDING_INVALID` | Invalid locale/text, color, palette shape, or incomplete color/palette pair |

## 6. Asset Endpoints

`kind` is the closed value `logo` or `favicon`.

### 6.1 `POST /branding/assets/{kind}`

Purpose: atomically create or replace one asset. Permission: `branding:write`.

The request is `multipart/form-data` with exactly one required file part named `file`. The maximum file size is 512 KiB. The declared multipart type is not trusted.

Positive allowlist after server detection:

| Kind | Accepted detected types |
| --- | --- |
| `logo` | `image/png`, `image/jpeg`, `image/svg+xml` |
| `favicon` | `image/png`, `image/vnd.microsoft.icon` |

PNG, JPEG, and ICO are detected by magic bytes. SVG is detected only by parsing XML with a parser that refuses DTD and entity declarations and requiring root `{http://www.w3.org/2000/svg}svg`. SVG containing `DOCTYPE`, entity declarations, `xml-stylesheet` processing instructions, scripts, SMIL animation elements (`animate`, `animateTransform`, `animateMotion`, `set`), event-handler attributes, external or `javascript:` links, nested `data:image/svg+xml` references, external images, or external fonts is rejected; it is never sanitized. Raster `data:image` URLs (`png`, `jpeg`, `gif`, `webp`) remain allowed.

Replacement and removal of prior bytes occur in one transaction. Audit detail includes kind, detected content type, byte size, and checksum, never bytes.

Response `201`:

```json
{
  "kind": "logo",
  "content_type": "image/svg+xml",
  "byte_size": 18420,
  "checksum": "2f3a...",
  "url": "/api/branding/assets/logo?v=2f3a..."
}
```

### 6.2 `GET /branding/assets/{kind}`

Purpose: read public asset bytes. No authentication.

Response `200` uses the detected `Content-Type` of the served bytes and:

```http
Cache-Control: public, max-age=31536000, immutable
ETag: "full-sha256-checksum"
X-Content-Type-Options: nosniff
```

The ETag is a strong validator. `If-None-Match` with the current checksum returns `304` without a body. For SVG, the response also includes:

```http
Content-Security-Policy: default-src 'none'; script-src 'none'; object-src 'none'; base-uri 'none'
```

The optional `v` query is a cache-busting checksum. A value that differs from the current checksum does not select historical bytes and does not change the response; asset history is not retained.

### 6.3 `DELETE /branding/assets/{kind}`

Purpose: remove the operator overlay for one kind. Permission: `branding:write`.

The HTTP method remains `DELETE`. The call deletes the stored overlay and does not write packaged seed bytes. Response is `204` with no body. Clients must not treat 204 as “no image”; a subsequent `GET /branding` returns the seed URL and `source` `seed` when packaged seeds are resolved. A successful write invalidates the public branding short cache and ETag.

The operation is idempotent: when there is no overlay, storage stays empty for that kind and presentation remains `seed`. A successful call writes a `site_branding` Management Audit Event even when the kind was already the seed or was absent. The logo is never substituted for the favicon.

When packaged seed resolution is skipped, DELETE removes the row and `GET /branding` may return a null URL for that kind.

### 6.4 Asset Errors

| Status | Problem Code | Condition |
| --- | --- | --- |
| `401` | `AUTH_UNAUTHENTICATED` | Mutation has no valid Session or User PAT |
| `403` | `AUTH_FORBIDDEN` | Mutation lacks `branding:write` |
| `404` | `BRANDING_ASSET_NOT_FOUND` | Public read has no asset for the kind |
| `413` | `BRANDING_ASSET_TOO_LARGE` | Upload exceeds 512 KiB |
| `415` | `BRANDING_ASSET_TYPE_UNSUPPORTED` | Detection fails or detected type is not allowed for the kind |
| `422` | `REQUEST_INVALID` | Unknown kind, missing/extra multipart part, or empty file |
| `422` | `BRANDING_ASSET_INVALID` | SVG XML is malformed or its root is not the SVG namespace element |
| `422` | `BRANDING_ASSET_UNSAFE` | SVG contains a forbidden active or external construct |

## 7. `POST /branding/reset`

Purpose: restore the complete default Refraq appearance. Permission: `branding:write`.

The request has no body. Unknown body content is rejected. The operation atomically removes the singleton configuration and both overlays. It does not insert packaged seed bytes. Response is `204` with no body. The Console requires a confirmation before calling it.

Reset is idempotent and always records a `site_branding` Management Audit Event. Subsequent `GET /branding` returns empty text maps and null color. When packaged seeds are resolved, both asset URLs are present and sources are `seed`. When packaged seed resolution is skipped, the response is the empty-store shape in §4.

Errors are `AUTH_UNAUTHENTICATED` (`401`), `AUTH_FORBIDDEN` (`403`), `REQUEST_INVALID` (`422`), or `BRANDING_WRITE_FAILED` (`503`).

## 8. General Errors And Audit

Store read failure is `BRANDING_READ_FAILED` (`503`); persistence or transactional replacement failure is `BRANDING_WRITE_FAILED` (`503`). These use Problem Details and carry `X-Request-ID` as specified by `docs/conventions-errors.md`.

Every successful `PUT`, asset upload, asset delete, and reset writes a Management Audit Event with `resource_type=site_branding`. The resource has no configurable attribution field, no history endpoint, and no API operation that removes Brand Attribution.

## 9. Non-Goals

- Locale negotiation or server-resolved brand text
- `Accept-Language` or locale-specific cache variants
- Attribution fields in read or write schemas
- Asset history, rollback, object storage, or logo-to-favicon conversion
- Arbitrary CSS, per-User skins, per-tenant themes, or dark/light asset sets
