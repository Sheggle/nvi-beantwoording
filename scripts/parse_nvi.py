"""
Parse NvI (Nota van Inlichtingen) PDF documents to extract Q&A tuples.

Output format: list of (section_nr, question, answer) tuples
"""

import re
from pathlib import Path
from pypdf import PdfReader


def parse_nvi(pdf_path: str | Path) -> list[tuple[str, str, str]]:
    """
    Parse an NvI PDF and extract Q&A pairs with their section numbers.

    Args:
        pdf_path: Path to the NvI PDF file

    Returns:
        List of (section_nr, question, answer) tuples
    """
    reader = PdfReader(pdf_path)
    results = []

    current_section = ""
    current_question_lines = []
    current_answer_lines = []
    in_qa_section = False

    # Column split position (approximate)
    COL_SPLIT = 55

    def save_qa():
        """Save current Q&A if valid."""
        nonlocal current_question_lines, current_answer_lines
        if current_question_lines and current_answer_lines:
            question = ' '.join(current_question_lines).strip()
            answer = ' '.join(current_answer_lines).strip()
            if question and answer:
                results.append((current_section, question, answer))
        current_question_lines = []
        current_answer_lines = []

    def question_is_complete():
        """Check if current question appears complete (ends with ?)."""
        if not current_question_lines:
            return False
        full_q = ' '.join(current_question_lines)
        return full_q.rstrip().endswith('?')

    for page in reader.pages:
        text = page.extract_text(extraction_mode='layout')
        lines = text.split('\n')

        for line in lines:
            # Skip empty lines
            if not line.strip():
                continue

            # Check for section headers like "1.2       Title" or "Subparagraaf 1.2.1"
            section_match = re.match(r'^(\d+(?:\.\d+)*)\s{2,}', line.strip())
            subpara_match = re.search(r'Subparagraaf\s+(\d+(?:\.\d+)*)', line)

            if subpara_match:
                save_qa()
                current_section = subpara_match.group(1)
                in_qa_section = False
                continue

            if section_match:
                # Check if this looks like a real section header (has title text after number)
                rest = line.strip()[len(section_match.group(0)):].strip()
                # Avoid matching things like page numbers or table entries
                if rest and len(rest) > 10 and not rest[0].isdigit():
                    save_qa()
                    current_section = section_match.group(1)
                    in_qa_section = False
                    continue

            # Check for Q&A header row
            if 'Vraag' in line and 'Antwoord' in line:
                save_qa()
                in_qa_section = True
                continue

            if not in_qa_section:
                continue

            # Skip page numbers (single numbers at end of page)
            if re.match(r'^\s*\d+\s*$', line):
                continue

            # Parse the two-column layout
            left_part = line[:COL_SPLIT].strip() if len(line) > COL_SPLIT else line.strip()
            right_part = line[COL_SPLIT:].strip() if len(line) > COL_SPLIT else ""

            # Detect new Q&A: if we have a complete question (ends with ?)
            # AND have some answer content, AND see new left content
            if left_part and question_is_complete() and current_answer_lines:
                save_qa()

            # Add content to current Q&A
            if left_part:
                current_question_lines.append(left_part)
            if right_part:
                current_answer_lines.append(right_part)

    # Don't forget the last Q&A
    save_qa()

    return results


def main():
    """Parse all NvI PDFs and print results."""
    data_dir = Path(__file__).parent.parent / "data"

    for pdf_path in sorted(data_dir.glob("NvI-*.pdf")):
        print(f"\n{'='*60}")
        print(f"Parsing: {pdf_path.name}")
        print('='*60)

        results = parse_nvi(pdf_path)

        print(f"\nTotal Q&A pairs extracted: {len(results)}")

        # Show section distribution
        sections = {}
        for section, q, a in results:
            sections[section] = sections.get(section, 0) + 1

        print(f"\nSection distribution ({len(sections)} unique sections):")
        for section in sorted(sections.keys(), key=lambda x: [int(n) for n in x.split('.')] if x else [0]):
            print(f"  {section or '(no section)'}: {sections[section]} Q&A pairs")

        # Show first 3 Q&A pairs as sample
        print("\nFirst 3 Q&A pairs:")
        for i, (section, question, answer) in enumerate(results[:3]):
            print(f"\n[{i+1}] Section: {section}")
            print(f"    Q: {question[:100]}..." if len(question) > 100 else f"    Q: {question}")
            print(f"    A: {answer[:100]}..." if len(answer) > 100 else f"    A: {answer}")


if __name__ == "__main__":
    main()
