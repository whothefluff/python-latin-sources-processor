"""
find_caps_after_punct.py

Scans an XML file's text content for punctuation marks followed by a
capital letter (e.g. "—Foo", "»Bar").

Usage:
    python find_caps_after_punct.py <path-to-xml>

Prints a count per punctuation mark and up to 100 sample contexts
(20 chars before and after each match).
"""

import re
import sys
import xml.etree.ElementTree as ET
from collections import Counter


def iter_text_nodes(elem):
    """Yield all text content of an XML element, depth-first, including tails.

    Covers both `elem.text` (content before the first child) and
    `child.tail` (content after each child's closing tag), which together
    are the only two places ElementTree stores text.
    """
    if elem.text:
        yield elem.text
    for child in elem:
        yield from iter_text_nodes(child)
        if child.tail:
            yield child.tail


def main():
    if len(sys.argv) < 2:
        sys.exit("usage: find_caps_after_punct.py <path-to-xml>")
    xml_file = sys.argv[1]

    with open(xml_file, "r", encoding="utf-8") as f:
        xml_string = f.read()

    root = ET.fromstring(xml_string)

    pattern = re.compile(r'([–—†\]⟩"\'‘’“”«»‹›…;:])\s*([A-Z])')
    mark_counts = Counter()
    hits = []

    for text in iter_text_nodes(root):
        for m in pattern.finditer(text):
            mark_counts[m.group(1)] += 1
            start = max(0, m.start() - 20)
            end = min(len(text), m.end() + 20)
            hits.append((m.group(1), text[start:end].replace("\n", " ")))

    print("Counts by mark:")
    for mark, count in mark_counts.most_common():
        print(f"  {mark!r}: {count}")

    print("\nSample contexts:")
    for mark, ctx in hits[:100]:
        print(f"  {mark!r}: ...{ctx}...")


if __name__ == "__main__":
    main()