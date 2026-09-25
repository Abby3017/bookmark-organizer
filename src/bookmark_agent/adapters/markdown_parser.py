import json
import re
from typing import List, Optional
from pathlib import Path
import yaml
from bookmark_agent.domain.bookmark_tree import BookmarkEntry
from models.article_summary import ArticleSummary, ProcessedArticleSummary
from utils.url_helpers import bookmark_id

def parse_bookmarks_file(filepath: str) -> tuple[List[BookmarkEntry], Optional[str]]:
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Extract batch-hint
    hint_match = re.search(r'<!--\s*batch-hint:\s*(.*?)\s*-->', content)
    batch_hint = hint_match.group(1).strip() if hint_match else None

    # Find the START and END markers
    start_tag = "<!-- BOOKMARKS START -->"
    end_tag = "<!-- BOOKMARKS END -->"
    
    start_idx = content.find(start_tag)
    end_idx = content.find(end_tag)

    if start_idx == -1 or end_idx == -1:
        return [], batch_hint
    
    bookmarks_section = content[start_idx + len(start_tag):end_idx].strip()
    
    entries = []
    current_entry = None
    
    lines = bookmarks_section.split("\n")
    for line in lines:
        line_s = line.strip()
        if not line_s:
            continue
            
        # Match [Title](URL)|date|tags
        match = re.match(r'^\[(.*?)\]\((.*?)\)\|(.*?)\|(.*)$', line_s)
        if match:
            title, url, date, tags_str = match.groups()
            tags = [t.strip() for t in tags_str.split(',') if t.strip()]
            id = bookmark_id(url)
            current_entry = BookmarkEntry(
                id = id,
                title=title,
                url=url,
                date=date,
                tags=tags
            )
            entries.append(current_entry)
        elif current_entry:
            # it's a note for the current entry if it doesn't match the regex
            current_entry.summary = (current_entry.summary or "") + line_s + "\n"
            
    return entries, batch_hint

def clear_processed_bookmarks(filepath: str, processed_count: int):
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    start_tag = "<!-- BOOKMARKS START -->"
    end_tag = "<!-- BOOKMARKS END -->"
    
    # Simple clear of everything between markers (assuming batch run)
    new_content = content[:content.find(start_tag) + len(start_tag)] + "\n\n" + content[content.find(end_tag):]
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(new_content)

def parse_processed_bookmarks():
    with open('config.yaml', 'r') as f:
                config = yaml.safe_load(f)
    processed_folder = config.get('processed_path')
    processed_dir = Path(processed_folder)

    assert processed_dir.exists(), (
        f"Processed folder does not exist: {processed_dir}"
    )

    assert processed_dir.is_dir(), (
        f"Processed path is not a folder: {processed_dir}"
    )

    batch_files = [
        path for path in processed_dir.iterdir()
        if path.is_file() and path.suffix == ".jsonl"
    ]

    assert batch_files, (
       f"No processed JSONL file found in: {processed_dir}"
    )

    assert len(batch_files) == 1, (
        f"Expected exactly one processed JSONL file in "
        f"{processed_dir}, found {len(batch_files)}"
    )

    summaries: list[ProcessedArticleSummary] = []

    with batch_files[0].open("r", encoding="utf-8") as file:
        for line_number, line in enumerate(file, start=1):
            if not line.strip():
                continue
            try:
                batch_record = json.loads(line)
                custom_id = batch_record.get("custom_id")
                content = (
                    batch_record["response"]["body"]["choices"][0]
                    ["message"]["content"]
                )
                response_data = json.loads(content)

                # The current batch file uses "bullet_points",
                # while ArticleSummary expects "bullets".
                response_data["bullets"] = response_data.pop(
                    "bullets",
                    response_data.get("bullets", []),
                )

                # The shown batch file does not contain tags.
                # Use an empty list until the model starts returning tags.
                response_data.setdefault("tags", [])

                summaries.append(
                    ProcessedArticleSummary(
                        id=custom_id,
                        summary=ArticleSummary.model_validate(response_data)
                    )
                )

            except (KeyError, IndexError, json.JSONDecodeError, ValueError) as exc:
                raise ValueError(
                    f"Invalid processed record at line {line_number} "
                    f"in {batch_files[0]}: {exc}"
                )
    return summaries