# Hugo Blog - JSON-LD Fix

## Problem

Hugo v0.154.5+ has a bug where `jsonify` outputs JSON as a double-encoded string instead of a raw JSON object. This causes Google Search Console to reject the structured data with the error:

```
Invalid top level element "string"
```

## Solution

This repository includes a post-processing script (`fix-jsonld.py`) that automatically fixes the JSON-LD structured data after Hugo builds the site.

## Building the Site

Instead of running `hugo` directly, use the build script:

```bash
./build.sh
```

This will:
1. Run Hugo to generate the site
2. Fix all JSON-LD blocks in the generated HTML files

## Manual Build

If you prefer to run the commands separately:

```bash
hugo
python3 fix-jsonld.py
```

## How It Works

The `fix-jsonld.py` script:
- Scans all HTML files in the `public/` directory
- Finds `<script type="application/ld+json">` blocks
- Detects if the JSON is double-encoded (a string containing JSON)
- Unwraps and properly formats the JSON as a valid JSON object
- Writes the fixed HTML back to disk

## Verification

To verify the fix worked, check any generated HTML file:

```bash
grep -A20 'application/ld+json' public/posts/*/index.html | head -30
```

The JSON-LD should start with `{` not `"{` (without the outer quotes).

## CI/CD Integration

### GitHub Actions (Already Configured!)

The `.github/workflows/hugo-pages.yml` has been updated to automatically fix JSON-LD during deployment:

```yaml
- name: Setup Python
  uses: actions/setup-python@v5
  with:
    python-version: '3.x'

- name: Build with JSON-LD fix
  env:
    HUGO_ENVIRONMENT: production
    HUGO_ENV: production
  run: |
    hugo --minify
    python3 fix-jsonld.py
```

### Other CI/CD Platforms

For other platforms, simply add Python to your environment and run both commands:

**GitLab CI:**
```yaml
build:
  image: klakegg/hugo:ext-alpine
  before_script:
    - apk add --no-cache python3
  script:
    - hugo --minify
    - python3 fix-jsonld.py
```

**Netlify:**
Add to `netlify.toml`:
```toml
[build]
  command = "hugo --minify && python3 fix-jsonld.py"
  publish = "public"
```

**Vercel:**
Add to `vercel.json`:
```json
{
  "buildCommand": "hugo --minify && python3 fix-jsonld.py"
}
```

## Notes

This is a workaround for a Hugo bug. Once Hugo fixes the `jsonify` output in a future version, this post-processing step can be removed.
