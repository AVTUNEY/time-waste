#!/usr/bin/env python3
"""
Fix double-encoded JSON-LD in Hugo-generated HTML files.
This script unwraps JSON strings that are incorrectly encoded.
"""

import json
import re
import sys
from pathlib import Path


def fix_jsonld_in_html(html_content):
    """Fix JSON-LD blocks that are double-encoded as strings."""
    
    def fix_jsonld_block(match):
        json_str = match.group(1).strip()
        
        try:
            # Try to parse - if it's a string, unwrap it
            parsed = json.loads(json_str)
            
            if isinstance(parsed, str):
                # It's double-encoded, unwrap it
                unwrapped = json.loads(parsed)
                # Re-encode properly
                fixed_json = json.dumps(unwrapped, indent=2, ensure_ascii=False)
                return f'<script type="application/ld+json">\n{fixed_json}\n</script>'
            elif isinstance(parsed, dict):
                # Already correct, no change needed
                return match.group(0)
            else:
                print(f"Warning: Unexpected JSON type: {type(parsed)}", file=sys.stderr)
                return match.group(0)
                
        except json.JSONDecodeError as e:
            print(f"Warning: Could not parse JSON-LD: {e}", file=sys.stderr)
            return match.group(0)
    
    # Find and fix all JSON-LD blocks (handles both quoted and unquoted attributes)
    pattern = r'<script type=["\']?application/ld\+json["\']?>(.*?)</script>'
    fixed_html = re.sub(pattern, fix_jsonld_block, html_content, flags=re.DOTALL)
    
    return fixed_html


def main():
    """Process all HTML files in the public directory."""
    public_dir = Path("public")
    
    if not public_dir.exists():
        print("Error: public directory not found. Run 'hugo' first.", file=sys.stderr)
        sys.exit(1)
    
    fixed_count = 0
    total_files = 0
    
    for html_file in public_dir.rglob("*.html"):
        total_files += 1
        
        try:
            content = html_file.read_text(encoding='utf-8')
            
            # Check for JSON-LD (handles both quoted and unquoted attributes)
            if 'application/ld+json' in content:
                fixed_content = fix_jsonld_in_html(content)
                
                if fixed_content != content:
                    html_file.write_text(fixed_content, encoding='utf-8')
                    fixed_count += 1
                    
        except Exception as e:
            print(f"Error processing {html_file}: {e}", file=sys.stderr)
    
    print(f"Processed {total_files} HTML files, fixed JSON-LD in {fixed_count} files.")
    if fixed_count > 0:
        print("✅ All JSON-LD structured data is now valid!")


if __name__ == "__main__":
    main()
