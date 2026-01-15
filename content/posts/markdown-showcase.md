---
title: "Markdown Showcase"
date: 2026-01-15T16:00:00+04:00
draft: false
type: "post"
tags: ["markdown", "examples", "reference"]
description: "A kitchen-sink post with common Markdown patterns and code examples."
---

This post is a grab-bag of Markdown patterns you can use in Hugo. Copy sections as a starting point.

## Headings

# H1 Title (usually the page title)
## H2 Section
### H3 Subsection
#### H4 Detail
##### H5 Small
###### H6 Tiny

## Text styles

Normal text, **bold**, *italic*, ***bold italic***, ~~strikethrough~~, and `inline code`.

You can also force a line break by ending a line with two spaces.  
Like this.

## Links

- External link: [Hugo](https://gohugo.io/)
- Internal link: [About](/about/)
- Auto link: <https://example.com>

## Lists

Unordered list:
- Item one
- Item two
  - Nested item
  - Another nested item
- Item three

Ordered list:
1. First step
2. Second step
3. Third step

Task list:
- [x] Write the draft
- [x] Add tags
- [ ] Publish

## Blockquotes

> A short quote can add emphasis.
>
> You can also make multi-line quotes.

## Horizontal rule

---

## Images

Inline image:

![Avatar sample](/images/avatar.svg)

Figure shortcode (Hugo):

{{< figure src="/images/avatar.svg" alt="Avatar sample" caption="Figure shortcode with caption" >}}

## Tables

| Column | Type | Notes |
| --- | --- | --- |
| title | string | Page title |
| date | time | Publish date |
| tags | array | Categories or labels |

## Code blocks

```bash
hugo server -D
```

```javascript
const posts = ["hello-world", "reading-log"];
const latest = posts.at(-1);
console.log(`Latest: ${latest}`);
```

```python
def slugify(text: str) -> str:
    return text.strip().lower().replace(" ", "-")
```

```go
package main

import "fmt"

func main() {
    fmt.Println("Hello, Hugo")
}
```

```html
<article class="post">
  <h1>Title</h1>
  <p>Intro text.</p>
</article>
```

```css
:root {
  --accent: #e4572e;
}
.post a:hover {
  color: var(--accent);
}
```

```toml
title = "My Hugo Site"
theme = "gokarna"

[params]
  showPostsOnHomePage = "recent"
```

```yaml
title: "Markdown Showcase"
tags:
  - markdown
  - examples
```

```json
{
  "title": "Markdown Showcase",
  "tags": ["markdown", "examples"]
}
```

## Footnotes

Here is a statement that needs a footnote.[^1]

[^1]: This is the footnote text.

## Inline HTML

<details>
  <summary>Click to expand</summary>
  <p>Hidden details can live in HTML blocks.</p>
</details>

## Escaping characters

Use a backslash to escape: \*not italic\*, \#not a heading.
