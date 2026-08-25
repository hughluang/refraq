# refraq Business Rules: Site Branding

## 1. Scope

This document defines **Site Branding**, the site-wide operator configuration that may replace Refraq's primary product mark while preserving immutable **Brand Attribution**. It covers ownership, localized text resolution, visual assets, color presentation, authorization, caching, reset, and audit. It does not define general theming or per-User presentation preferences.

Related boundaries:

- Terminology: `docs/glossary.md` and root `CONTEXT.md`.
- HTTP: `docs/api-contracts-branding.md`.
- Console information architecture: `docs/business-management-console.md`.
- Errors: `docs/conventions-errors.md`.

## 2. Resource And Ownership

**Site Branding** is one singleton resource for the whole deployment. The Management Foundation owns it as the `branding` language unit under `backend/admin/`; it is not a **System Parameter**, an Account Center preference, a product-domain entity, or a per-tenant resource.

The resource may configure:

- `brand_names`: locale-to-text map
- `taglines`: locale-to-text map
- one logo shared by the top bar and login page
- one favicon, independent from the logo
- `primary_color` and its ten derived `primary_shades`
- `show_logo` and `show_brand_name_with_logo`, independent display choices applied consistently to the top bar and login page

A logo is suitable for both a roughly 24–28 pixel top-bar height and a larger login presentation. The product does not provide separate placement-specific logos.

### 2.1 Display Choices

`show_logo` and `show_brand_name_with_logo` are independent. Both default to true. Both apply to the top bar and login page; unsaved Console changes affect only the branding page preview.

`show_logo` controls whether the shared logo is painted. It does not change overlay storage, seed resolution, or `logo_url`. Turning it off is not deleting the overlay; restoring the packaged seed remains a separate asset delete. Favicon presentation is independent.

`show_brand_name_with_logo` controls whether the resolved brand name is painted. The two fields are not validated as a pair: both may be false, leaving the primary product mark empty on those surfaces. Tagline resolution is unchanged. Brand Attribution remains on the login footer and in About.

Explicit null on write restores that field's default. Whole-resource reset restores both to true.

## 3. Localized Product Mark

### 3.1 Unresolved Public Representation

The public branding representation carries `brand_names` and `taglines` as unresolved locale maps. Locale resolution is a consumer contract because the site default locale and live locale switch belong to the frontend. The representation is independent of request locale: clients do not send a locale parameter, and responses do not vary on `Accept-Language`.

Map keys are supported Console UI locale codes and correspond to the consumer's locale catalog. Values are trimmed, non-empty plain text. Brand names are at most 80 characters and taglines are at most 160 characters. Markdown and HTML are not supported.

### 3.2 Brand Name Fallback

For current locale `L`, a consumer resolves the brand name in this order:

1. Non-empty `brand_names[L]`.
2. Non-empty entry for `NEXT_PUBLIC_DEFAULT_LOCALE`.
3. The first non-empty entry encountered in `LOCALE_CATALOG` order, skipping locales already considered.
4. `Refraq`.

A newly supported locale is added to the Console locale catalog and backend supported-locale set before branding accepts that key.

### 3.3 Tagline Fallback

A site is **brand-configured** exactly when `brand_names` contains at least one non-empty value in any locale. A primary color, palette, logo, favicon, or display choice alone does not make it brand-configured.

- If the site is not brand-configured, the consumer uses Refraq's localized default product-positioning tagline.
- If the site is brand-configured, the consumer uses only non-empty `taglines[L]` for the current locale.
- If that current-locale entry is absent, the resolved tagline is empty. It never falls back to another customer locale or to Refraq's default tagline.

Absence is therefore sufficient to express "no tagline"; the model does not add a third text state.

## 4. Brand Attribution

**Brand Attribution** always identifies `Refraq` as the technology provider. Site Branding cannot replace or remove it.

The invariant is enforced by contract shape: branding write schemas contain no attribution field, and the public branding representation does not return one. The frontend owns the constant brand name and link; surrounding localized copy uses an interpolation placeholder for `Refraq` so the brand remains Latin-script text in every locale.

Attribution appears in the login footer and in About within the top-bar user menu. About is not structural navigation, does not enter the Console Module catalog, and requires no branding Permission. This invariant protects the supported product and management API. A downstream source fork can alter frontend constants and is outside the enforcement boundary.

## 5. Visual Assets

### 5.1 Accepted Assets

The positive allowlist is:

| Kind | Accepted detected content types | Maximum size |
| --- | --- | --- |
| `logo` | `image/png`, `image/jpeg`, `image/svg+xml` | 512 KiB |
| `favicon` | `image/png`, `image/vnd.microsoft.icon` | 512 KiB |

The favicon is independent. Packaged seed files live with the Site Branding language unit and are the original default bytes for both kinds. Storage holds only operator overlays: a stored row is the overlay. Absence of a row means that kind uses the current packaged seed file. Deleting a kind removes the overlay and does not write seed bytes into storage; it never substitutes the shared logo for the favicon. Whole-resource reset clears configuration and both overlays. Subsequent reads use the current packaged files. Origin `user` is read-time presentation of a stored overlay; `seed` is read-time presentation of the current packaged file when no overlay exists. Origin is not persisted and is not inferred from checksum.

### 5.2 Detection And Rejection

The server does not trust the multipart `Content-Type`. It detects PNG (`89 50 4E 47`), JPEG (`FF D8 FF`), and ICO (`00 00 01 00`) by magic bytes and persists the detected type.

SVG has no magic-byte branch. It is accepted only when a parser that refuses DTD and entity declarations parses the document and the root element is `{http://www.w3.org/2000/svg}svg`. The server rejects SVG rather than sanitizing it when it contains:

- `DOCTYPE` or entity declarations
- `xml-stylesheet` processing instructions
- `script` elements
- SMIL animation elements (`animate`, `animateTransform`, `animateMotion`, `set`)
- event-handler attributes whose local name starts with `on`
- `href` or `xlink:href` values that are external or use `javascript:`
- nested `data:image/svg+xml` (or any non-raster `data:`) references
- externally loaded fonts or images

Raster `data:image` URLs (`png`, `jpeg`, `gif`, `webp`) and fragment `#` references are allowed. Paths, gradients, and inline styles are allowed when they do not introduce those rejected constructs. Any unrecognized type, kind/type mismatch, empty upload, oversize upload, malformed SVG, or unsafe SVG is rejected. Asset replacement is atomic by kind and leaves no orphaned bytes.

## 6. Primary Color

`primary_color` accepts a six-digit hexadecimal RGB color in `#RRGGBB` form. The Console generates exactly ten `primary_shades` with `@mantine/colors-generator` whenever it saves a primary color and submits both fields together.

The backend validates that `primary_shades` contains exactly ten valid `#RRGGBB` strings. It does not generate the palette, compare shades with `primary_color`, or clamp the selected color. The Console is the sole product author of the derived palette. It warns when button text contrast would not meet WCAG 2.1 criterion 1.4.3 at 4.5:1, but the warning does not block saving. Runtime presentation uses the persisted shades and automatic contrast.

## 7. Authorization And Console

`branding:read` controls visibility of the Site Branding Console Module at `/console/branding`. `branding:write` controls every configuration, asset, and reset mutation. These Permissions are independently grantable and are not aliases for `settings:write`.

The locked `super_admin` System Role receives new Permission catalog entries by definition. Existing custom Roles do not gain either Permission automatically.

The public representation and asset reads are intentionally unauthenticated because the login page and browser metadata need branding before a Session exists. This exposes the configured customer name and public visual assets to unauthenticated visitors; that disclosure is an accepted consequence of a branded login surface.

Unsaved Console changes affect only the branding page preview. The top bar, login page, other Console pages, and other Users continue to use the last saved resource.

## 8. Caching And Consistency

The public branding representation uses a process-local cache of approximately 30 seconds and HTTP `Cache-Control: public, max-age=30, stale-while-revalidate=60` with a content-derived ETag. A successful write invalidates the writer process's copy; other processes may present the prior value until their short cache expires.

Versioned asset URLs include the asset checksum. Asset responses use a strong checksum ETag and `Cache-Control: public, max-age=31536000, immutable`. Changes produce a new checksum URL instead of mutating cached content at the old versioned URL.

Consumers already displaying branding may retain it until their next page render or refresh. Branding fetch failure must not prevent the application or login page from rendering. When an asset URL is absent, the consumer omits that kind. A first-party consumer also omits painting the logo when `show_logo` is false, even when `logo_url` is present. It must not substitute the logo URL for the favicon or the favicon URL for the logo.

## 9. Mutation, Reset, And Audit

Configuration fields use present-null semantics: omission preserves the stored field, while explicit null clears it to its product default. Locale maps are replaced as whole fields; `{}` or null clears the map, and removing one key from the submitted map clears that locale. `primary_color` and `primary_shades` are set or cleared as a pair.

Operators may clear individual configuration fields or restore either asset to the packaged seed by deleting the overlay. A confirmed whole-resource reset removes all configuration and both overlays. Subsequent reads present the current packaged logo and favicon, restoring the complete Refraq default appearance.

Every successful configuration write, asset upload or delete, and whole-resource reset produces a **Management Audit Event** with `resource_type=site_branding`. Asset audit detail records only kind, byte size, checksum, detected content type, and origin; it never records asset bytes.

## 10. Non-Goals

- Per-User skins, per-tenant themes, arbitrary theme workshops, or custom CSS
- Separate top-bar and login logos, dark/light asset variants, or generated favicons
- Login backgrounds, email branding, PWA identity, legal links, or branding version history
- Object storage for the two bounded site assets
- Configurable, licensed, or OEM-dependent Brand Attribution
