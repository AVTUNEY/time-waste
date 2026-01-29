# Quick Reference Card 🚀

## Local Build Commands

```bash
# Full build with minification
./build.sh --minify

# Or step by step
hugo --minify
python3 fix-jsonld.py
```

## Deploy to GitHub Pages

```bash
git add .
git commit -m "Fix JSON-LD structured data"
git push
```

GitHub Actions will automatically:
1. Build with Hugo
2. Fix JSON-LD
3. Deploy to Pages

## Verify JSON-LD

```bash
# Check a specific page
python3 << 'PY'
import json, re
from pathlib import Path

html = Path("public/index.html").read_text()
match = re.search(r'<script type=["\']?application/ld\+json["\']?>(.*?)</script>', html, re.DOTALL)
if match:
    data = json.loads(match.group(1).strip())
    print(f"✅ Valid! Type: {data.get('@type')}")
PY
```

## Files to Commit

- ✅ `fix-jsonld.py` - The fix script
- ✅ `build.sh` - Local build helper
- ✅ `.github/workflows/hugo-pages.yml` - CI/CD config
- ✅ `JSON-LD-FIX-README.md` - Documentation
- ✅ `INTEGRATION-SUMMARY.md` - Integration guide
- ✅ `QUICK-REFERENCE.md` - This file

## Troubleshooting

**Issue:** JSON-LD still showing as string after build
**Fix:** Run `python3 fix-jsonld.py`

**Issue:** GitHub Actions fails
**Fix:** Check that both `fix-jsonld.py` and `.github/workflows/hugo-pages.yml` are committed

**Issue:** Want to test without deploying
**Fix:** Use `hugo --minify && python3 fix-jsonld.py` locally

## Google Search Console

After deployment:
1. Go to Google Search Console
2. Navigate to "Enhancements" → "Unparsable structured data"
3. Click "Validate Fix"
4. Wait 24-48 hours for re-crawl

The error "Invalid top level element 'string'" will be resolved! ✅
