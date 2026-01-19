"""
Parse Inkoopbeleid (Policy) PDF documents to extract section tuples.

Output format: list of (section_nr, title, text) tuples
"""

import re
from pathlib import Path
from pypdf import PdfReader


def parse_inkoopbeleid(pdf_path: str | Path) -> list[tuple[str, str, str]]:
    """
    Parse an Inkoopbeleid PDF and extract sections with their numbers and text.

    Args:
        pdf_path: Path to the Inkoopbeleid PDF file

    Returns:
        List of (section_nr, title, text) tuples
    """
    reader = PdfReader(pdf_path)
    results = []

    current_section = ""
    current_title = ""
    current_text_lines = []

    # Skip table of contents pages (typically pages 5-7)
    # We'll detect TOC by looking for many section references without full text

    def save_section():
        """Save current section if valid."""
        nonlocal current_section, current_title, current_text_lines
        if current_section and current_title:
            text = ' '.join(current_text_lines).strip()
            # Clean up multiple spaces
            text = re.sub(r'\s+', ' ', text)
            if text:  # Only save if there's actual content
                results.append((current_section, current_title, text))
        current_section = ""
        current_title = ""
        current_text_lines = []

    def is_section_header(line: str) -> tuple[str, str] | None:
        """
        Check if line is a section header.
        Returns (section_nr, title_start) if it's a header, None otherwise.
        """
        line = line.strip()
        if not line:
            return None

        # Match section number pattern: 1, 1.1, 1.2.3, etc.
        # Must be followed by space(s) and a capital letter or substantial text
        match = re.match(r'^(\d+(?:\.\d+)*)\s+([A-Z].*)$', line)
        if not match:
            # Also try with period after number: "1. Title"
            match = re.match(r'^(\d+(?:\.\d+)*)\.?\s+([A-Z].*)$', line)

        if match:
            section_nr = match.group(1)
            title_start = match.group(2)

            # Filter out false positives:

            # 1. Years (2024, 2025, etc.) - these are 4-digit numbers
            if len(section_nr) == 4 and section_nr.startswith('20'):
                return None

            # 2. Section numbers that are too deep (more than 4 levels) are suspicious
            parts = section_nr.split('.')
            if len(parts) > 4:
                return None

            # 3. Numbers without dots (like 1, 2, 10, 15) are often list items
            # Real chapter headers have formal titles without articles at start
            # and typically span multiple words describing a topic
            if '.' not in section_nr:
                # List item indicators: starts with common Dutch articles/words
                # that typically begin sentences, not titles
                list_item_starts = [
                    'De', 'Het', 'Een', 'We', 'Wij', 'Er', 'Dit', 'Dat',
                    'Bij', 'In', 'Op', 'Om', 'Als', 'Indien', 'Wanneer',
                    'Voor', 'Met', 'Aan', 'Van', 'Uit', 'Naar', 'Elke',
                    'Alle', 'Bewezen', 'Binnen', 'Bestaand', 'Allereerst',
                    'Vervolgens', 'Tot', 'Hierbij', 'Passend', 'Controle',
                    'Nieuwe', 'Uitgangspunt', 'Uiterste', 'Definitieve',
                    'Deadline', 'Vervaltermijn', 'Energieprestatie',
                    'Medicatieoverdracht', 'MedMij', 'Mitz', 'NZa',
                    'Getekende', 'Meest', 'Landelijke', 'Aanvaardbare', 'U',
                    'Klanten', 'Meer', 'Borgen', 'Mogelijkheid', 'Openstellen',
                    'Terugkoppeling', 'T', 'Daar',  # T for "T erugkoppeling" (OCR artifact)
                    'Indien', 'Definitieve',  # procedure list items
                    'Daarom', 'Naast', 'Beschikbaarheid', 'Hoewel', 'NZ', 'Me', 'V',
                    # OCR artifacts: "NZ a" = "NZa", "Me er" = "Meer", "V oor" = "Voor"
                    'Bekendmaking', 'Publicatie', 'Datum',  # procedure table items
                ]
                first_word = title_start.split()[0] if title_start.split() else ''
                # Strip trailing punctuation for comparison
                first_word_clean = first_word.rstrip(':;,.')
                if first_word_clean in list_item_starts:
                    return None

                # Also filter short titles that don't look like chapter headers
                if len(title_start) < 40:
                    return None

            return (section_nr, title_start)

        return None

    def is_page_number(line: str) -> bool:
        """Check if line is just a page number."""
        return bool(re.match(r'^\s*\d{1,3}\s*$', line))

    def is_toc_page(page_text: str) -> bool:
        """Check if this looks like a table of contents page."""
        lines = page_text.strip().split('\n')
        # TOC pages have many lines that are just section refs or very short
        short_lines = sum(1 for l in lines if len(l.strip()) < 100)
        # And few long paragraph lines
        long_lines = sum(1 for l in lines if len(l.strip()) > 100)
        # TOC typically has ratio of short:long > 5
        return len(lines) > 10 and short_lines > 5 * max(long_lines, 1)

    for page_num, page in enumerate(reader.pages):
        text = page.extract_text()

        # Skip likely TOC pages
        if is_toc_page(text):
            continue

        lines = text.split('\n')

        for line in lines:
            # Skip page numbers
            if is_page_number(line):
                continue

            # Skip empty lines
            if not line.strip():
                continue

            # Check for section header
            header = is_section_header(line)
            if header:
                section_nr, title_start = header

                # Save previous section
                save_section()

                # Start new section
                current_section = section_nr
                current_title = title_start
                continue

            # If we're in a section, accumulate text
            if current_section:
                # Check if this line continues the title (no section yet, short text)
                if not current_text_lines and len(current_title) < 60:
                    # This might be title continuation (multi-line titles)
                    # Check if it looks like title continuation (ends without period, starts capitalized)
                    stripped = line.strip()
                    if stripped and not current_title.rstrip().endswith('.'):
                        current_title += ' ' + stripped
                        continue

                current_text_lines.append(line.strip())

    # Don't forget the last section
    save_section()

    return results


def main():
    """Parse all Inkoopbeleid PDFs and print results."""
    data_dir = Path(__file__).parent.parent / "data"

    for pdf_path in sorted(data_dir.glob("Inkoopbeleid-*.pdf")):
        print(f"\n{'='*60}")
        print(f"Parsing: {pdf_path.name}")
        print('='*60)

        results = parse_inkoopbeleid(pdf_path)

        print(f"\nTotal sections extracted: {len(results)}")

        # Show section distribution
        depths = {}
        for section, title, text in results:
            depth = len(section.split('.'))
            depths[depth] = depths.get(depth, 0) + 1

        print(f"\nSection depth distribution:")
        for depth in sorted(depths.keys()):
            print(f"  Level {depth}: {depths[depth]} sections")

        # Show first 3 sections as sample
        print("\nFirst 3 sections:")
        for i, (section, title, text) in enumerate(results[:3]):
            print(f"\n[{i+1}] Section {section}: {title[:60]}...")
            print(f"    Text: {text[:150]}..." if len(text) > 150 else f"    Text: {text}")

        # Show last section
        print("\nLast section:")
        section, title, text = results[-1]
        print(f"Section {section}: {title[:60]}...")
        print(f"Text: {text[:150]}..." if len(text) > 150 else f"Text: {text}")


if __name__ == "__main__":
    main()
