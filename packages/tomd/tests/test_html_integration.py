"""Integration tests for lib.html.convert_html."""

import re
from pathlib import Path

from tomd.lib.html import convert_html


def _write(tmp: Path, name: str, html: str) -> Path:
    p = tmp / name
    p.write_text(html, encoding="utf-8")
    return p


MPARK_WITH_BODY = """<!DOCTYPE html>
<html><head><meta charset="utf-8"/></head><body>
<header id="title-block-header">
<h1 class="title">Paper Title</h1>
<table>
<tr><td>Document #:</td><td>P9999R0</td></tr>
<tr><td>Date:</td><td>2026-04-01</td></tr>
</table>
</header>
<p>Body paragraph one.</p>
</body></html>
"""


def test_convert_html_happy_path(tmp_path):
    path = _write(tmp_path, "x.html", MPARK_WITH_BODY)
    md, prompts = convert_html(path)
    assert prompts is None
    assert md.startswith("---")
    assert "P9999R0" in md
    assert "Body paragraph one." in md
    assert md.endswith("\n")
    assert "\n\nBody paragraph one." in md


def test_convert_html_unknown_generator_prompts(tmp_path):
    html = "<html><body><p>Only content</p></body></html>"
    path = _write(tmp_path, "u.html", html)
    md, prompts = convert_html(path)
    assert isinstance(prompts, list) and prompts
    joined = "\n".join(prompts)
    assert "HTML-to-Markdown conversion" in joined
    assert "Unrecognized" in joined
    assert "Only content" in md


def test_convert_html_body_headings_start_at_h2(tmp_path):
    # H1-rooted body sections are shifted to H2 (title is the only H1), and a
    # leading body heading that duplicates the title is dropped even though it
    # now arrives as H2 rather than H1.
    html = """<!DOCTYPE html><html><head></head><body>
<header id="title-block-header">
<h1 class="title">My Great Paper</h1>
<table><tr><td>Document #:</td><td>P7R0</td></tr></table>
</header>
<h1>My Great Paper</h1>
<p>Intro.</p>
<h1>Section One</h1>
<p>Body.</p>
<h2>Subsection</h2>
</body></html>"""
    path = _write(tmp_path, "shift.html", html)
    md, _ = convert_html(path)
    body = md.split("---", 2)[-1]
    assert not re.search(r"(?m)^# ", body)
    assert "## Section One" in md
    assert "### Subsection" in md
    assert "## My Great Paper" not in md
    assert md.count("My Great Paper") == 1


def test_convert_html_unicode_preserved(tmp_path):
    html = """<!DOCTYPE html><html><body>
<header id="title-block-header">
<h1 class="title">T\u00fctle</h1>
<table><tr><td>Document #:</td><td>P1R0</td></tr></table>
</header>
<p>Body \u00fc</p>
</body></html>"""
    path = _write(tmp_path, "enc.html", html)
    md, prompts = convert_html(path)
    assert prompts is None
    assert "\xfc" in md


def test_convert_html_metadata_only_empty_body(tmp_path):
    html = """<html><body>
<header id="title-block-header">
<h1 class="title">Solo</h1>
<table><tr><td>Document #:</td><td>P2R0</td></tr></table>
</header>
</body></html>"""
    path = _write(tmp_path, "meta.html", html)
    md, prompts = convert_html(path)
    assert prompts is None
    assert md.startswith("---")
    assert "Solo" in md or "solo" in md.lower()


def test_convert_html_title_with_embedded_dashes(tmp_path):
    html = """<!DOCTYPE html>
<html><head><meta charset="utf-8"/></head><body>
<header id="title-block-header">
<h1 class="title">Before --- After</h1>
<table>
<tr><td>Document #:</td><td>P8888R0</td></tr>
<tr><td>Date:</td><td>2026-04-01</td></tr>
</table>
</header>
<p>Paragraph after title.</p>
</body></html>"""
    path = _write(tmp_path, "dashes.html", html)
    md, prompts = convert_html(path)
    assert prompts is None
    assert "Before --- After" in md
    assert "Paragraph after title." in md
    body_start = md.find("---", 4)
    assert body_start >= 0
    body = md[body_start:]
    closing = body.find("\n---", 1)
    assert closing >= 0
    body_text = body[closing + 4 :]
    assert "# Before --- After" not in body_text


def test_convert_html_front_matter_then_body_separator(tmp_path):
    path = _write(tmp_path, "sep.html", MPARK_WITH_BODY)
    md, _ = convert_html(path)
    idx = md.find("Body paragraph one.")
    assert idx > 0
    before = md[:idx]
    assert before.rstrip().endswith("---")
    assert "\n\n" in md[: idx + 1]


def test_unknown_no_warning_when_table_metadata_found(tmp_path):
    """unknown generator: warning suppressed when metadata was extracted."""
    html = """<!DOCTYPE html><html><body>
<h1>Some Paper</h1>
<table>
  <tr><th>Document number:</th><td>P9001R0</td></tr>
  <tr><th>Date:</th><td>2026-04-01</td></tr>
</table>
<p>Body text here.</p>
</body></html>"""
    path = _write(tmp_path, "unknown_meta.html", html)
    md, prompts = convert_html(path)
    assert prompts is None, "warning should be suppressed when metadata was found"
    assert "P9001R0" in md


def test_unknown_warning_preserved_when_no_metadata(tmp_path):
    """unknown generator, no recognizable metadata: warning IS emitted.

    This is the failure-detection test - extraction failed, and tomd correctly
    signals it via the prompts file so the user knows.
    """
    html = """<!DOCTYPE html><html><body>
<p>This has no document number, date, or any WG21 metadata at all.</p>
<p>Just pure prose with nothing recognizable.</p>
</body></html>"""
    path = _write(tmp_path, "unknown_no_meta.html", html)
    md, prompts = convert_html(path)
    assert isinstance(prompts, list) and prompts, (
        "warning should be present when extraction failed"
    )
    assert any("Unrecognized" in p for p in prompts)


_IMG_POSITIONS_HTML = """<!DOCTYPE html><html><head></head><body>
<header id="title-block-header">
<h1 class="title">Img Paper</h1>
<table><tr><td>Document #:</td><td>P9R0</td></tr></table>
</header>
<p>Before.</p>
<img src="data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42nNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==" alt="block level alt">
<p>Inline <img src="data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42nNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==" alt="inline alt"> shot.</p>
<figure><img src="https://example.com/fig.png" alt="figure alt"><figcaption>Figure 1: visible caption</figcaption></figure>
</body></html>"""


def test_convert_html_never_emits_image_syntax(tmp_path):
    """#408: <img> never reaches markdown - no data: URI, no remote URL,
    no image syntax, no alt text - in block, inline, and figure positions.
    Visible caption text (<figcaption>) survives as normal text."""
    path = _write(tmp_path, "img_positions.html", _IMG_POSITIONS_HTML)
    md, _ = convert_html(path)
    assert "![" not in md
    assert "data:image" not in md
    assert "example.com/fig.png" not in md
    assert "block level alt" not in md
    assert "inline alt" not in md
    assert "figure alt" not in md
    assert "Before." in md
    assert "Inline" in md and "shot." in md
    assert "Figure 1: visible caption" in md


def test_convert_html_with_manifest_still_emits_no_image_syntax(tmp_path):
    """#408: even with a mailing manifest present, markdown carries no
    image reference - the manifest only feeds sidecar accounting and the
    truncation marker. A real entry with a stored filename and alt text
    must leak neither into the markdown; the truncation marker fires
    when the result says the source was capped."""
    from tomd.domain.image import ExtractedImage
    from tomd.lib.html.images import HtmlImagesResult

    path = _write(tmp_path, "img_manifest.html", _IMG_POSITIONS_HTML)
    result = HtmlImagesResult(
        images=[
            ExtractedImage(
                page=0, index_on_page=1, ext="png", bytes=b"",
                bbox=(0.0, 0.0, 0.0, 0.0),
                suggested_alt="manifest alt text",
                stored_filename="p9999r0-fig0-1.png",
                xref=0,
            ),
        ],
        source_image_count=3,
        images_truncated=True,
    )
    md, _ = convert_html(path, html_images_result=result)
    assert "![" not in md
    assert "data:image" not in md
    assert "example.com/fig.png" not in md
    assert "p9999r0-fig0-1.png" not in md
    assert "manifest alt text" not in md
    assert "Figure 1: visible caption" in md
    # The truncation marker discloses on-disk accounting without any
    # image syntax.
    assert "tomd:images-truncated" in md
    assert "kept 1 of 3" in md


def test_mixed_code_table_drops_img_nested_in_allowed_wrapper(tmp_path):
    """#408: the mixed-code-table path serializes allowed inline tags
    (<span>, <a>, ...) as raw HTML. An <img> nested inside such a
    wrapper must not ride along - str(child) would otherwise leak the
    raw tag and a data: URI into the cell."""
    html = (
        "<html><head><title>T</title></head><body>"
        "<table><tr>"
        "<td><pre><code>int x;</code></pre></td>"
        '<td>note <span class="k"><img src="data:image/png;base64,QUJD"'
        ' alt="cell alt"></span> end</td>'
        "</tr></table>"
        "</body></html>"
    )
    path = _write(tmp_path, "table_img.html", html)
    md, _ = convert_html(path)
    assert "int x;" in md
    assert "note" in md and "end" in md
    assert "![" not in md
    assert "data:image" not in md
    assert "<img" not in md
    assert "cell alt" not in md
