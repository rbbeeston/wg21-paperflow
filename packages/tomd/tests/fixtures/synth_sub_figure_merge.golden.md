---
title: "Synthetic Sub-Figure Merge Fixture"
reply-to:

---

<!-- tomd:summary tables=0 trusted=0 flagged=0 likely=0 marked=0 confidence=n/a unfamiliarity=0.40 -->

This fixture tests that two vertically-stacked vector clusters separated by a sub-caption line are merged into a single image by the _merge_sub_figure_clusters pass in vector_images.py.

The pipeline must produce exactly one vector image spanning both panels, with (a) and (b) sub-captions as italic paragraphs below.

*Figure 1: Multi-panel sub-figures*

*(a) Upper sub-figure*

*(b) Lower sub-figure*

The two panels above are rendered as a merged vector image. Sub-captions (a) and (b) appear as italic paragraphs below the image.
