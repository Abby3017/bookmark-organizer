import re
import pickle
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from pathlib import Path

# sys.path.append("/Users/abhinavkumar/prj/src")
from utils.colors import error


@dataclass
class BookmarkNode:
    """A node in the bookmark tree — can be a file, section, or subsection."""
    name: str
    path: str
    file_path: Optional[str] = None    # set only on file-level nodes
    children: Dict[str, "BookmarkNode"] = field(default_factory=dict)
    sections: Dict[str, "SectionNode"] = field(default_factory=dict)
    total_entries: int = 0


@dataclass
class SectionNode:
    """A section (## heading) within a bookmark file."""
    name: str = "default"
    entries: List["BookmarkEntry"] = field(default_factory=list)

    @property
    def entry_count(self) -> int:
        return len(self.entries)


@dataclass
class BookmarkEntry:
    title: str
    url: str
    id: Optional[str] = None
    date: Optional[str] = None
    tags: Optional[List[str]] = None
    notes: List[str] = field(default_factory=list)
    summary: Optional[str] = None


class BookmarkTree:
    """
    Trie-like tree structure for the bookmark hierarchy.

    Supports:
      - O(1) path resolution: tree.find("learn/language/python")
      - O(1) entry count per section: node.sections["Libraries"].entry_count
    """

    def __init__(self):
        self.root = BookmarkNode(name="root", path="")

    def insert_file(self, concept_name: str, file_path: str) -> BookmarkNode | None:
        """Insert a file node at the given tree path, creating intermediate nodes.

        Parses the markdown file and populates sections with bookmark entries.
        Entries before any ## heading go into a 'default' section.
        """
        bookmark_path = Path(file_path)

        if not bookmark_path.exists():
            error(f"File not found: {file_path}")
            return None

        if concept_name not in self.root.children:
            self.root.children[concept_name] = BookmarkNode(
                name=concept_name, path=concept_name
            )
        node = self.root.children[concept_name]
        node.file_path = file_path

        with bookmark_path.open('r', encoding='utf-8') as f:
            content = f.read()

        current_section = "default"
        current_entries = []

        for line in content.split('\n'):
            line_s = line.strip()
            if not line_s:
                continue

            if line_s.startswith('# ') and not line_s.startswith('## '):
                continue

            if line_s.startswith('## '):
                if current_entries:
                    self._populate_section(
                        node, current_section, current_entries)
                    current_entries = []

                current_section = line_s[3:].strip()
                continue

            match = re.match(
                r'^-?\s*\[(.*?)\]\((.*?)\)(?:\|(.*?))?(?:\|(.*?))?$', line_s)
            if match:
                title, url = match.group(1), match.group(2)
                date = match.group(3) or None
                tags_str = match.group(4) or ""
                tags = [t.strip() for t in tags_str.split(
                    ',') if t.strip()] if tags_str else []

                entry = BookmarkEntry(
                    title=title,
                    url=url,
                    date=date,
                    tags=tags,
                )
                current_entries.append(entry)
            else:
                if entry is not None:
                    entry.notes.append(line_s)

        # save remaining entries to the last section
        if current_entries:
            self._populate_section(node, current_section, current_entries)

        return node

    def _populate_section(self, node: BookmarkNode, section_name: str,
                          entries: List[BookmarkEntry]):
        """Add entries to a section on the node and update total_entries."""
        sec = node.sections.setdefault(
            section_name, SectionNode(name=section_name))
        sec.entries.extend(entries)
        node.total_entries += len(entries)

    def find(self, bookmark_node: str) -> Optional[BookmarkNode]:
        """Resolve a dotted path to a node in O(depth)."""
        node = self.root.children.get(bookmark_node)
        if not node:
            error(f"Bookmark node '{bookmark_node}' not found in tree.")
            return None
        return node

    def add_entry(self, bookmark_node: str, section: str, entry: BookmarkEntry):
        """Add a bookmark entry and incrementally update counts."""
        node = self.find(bookmark_node)
        if not node:
            return

        sec = node.sections.setdefault(section, SectionNode(name=section))
        sec.entries.append(entry)
        node.total_entries += 1

    def visualize(self) -> str:
        lines = ["root"]
        self._visualize_node(self.root, lines, prefix="")
        return "\n".join(lines)

    def _visualize_node(self, node: BookmarkNode, lines: list,
                        prefix: str, is_last: bool = True):
        """Recursively build ASCII tree bookmarks for a node."""
        # Draw children
        children = list(node.children.values())
        for i, child in enumerate(children):
            is_last_child = (i == len(children) - 1)
            connector = "└── " if is_last_child else "├── "
            lines.append(f"{prefix}{connector}{child.name}"
                         f" ({child.total_entries} entries)")

            extension = "    " if is_last_child else "│   "
            sections = list(child.sections.values())
            for j, sec in enumerate(sections):
                is_last_sec = (j == len(sections) - 1)
                sec_connector = "└── " if is_last_sec else "├── "
                lines.append(f"{prefix}{extension}{sec_connector}"
                             f"** {sec.name} ({sec.entry_count})")

                for k, entry in enumerate(sec.entries):
                    is_last_entry = (
                        k == len(sec.entries) - 1)
                    ent_connector = "└── " if is_last_entry else "├── "
                    lines.append(f"{prefix}{extension}    {ent_connector}"
                                 f"[{entry.title}]({entry.url[:40]}...)")

            self._visualize_node(child, lines,
                                 prefix + extension, is_last_child)

    def save_tree(self, cache_path: str):
        with open(cache_path, "wb") as f:
            pickle.dump(self, f)

def load_tree(cache_path: str) -> BookmarkTree:
    with open(cache_path, "rb") as f:
        return pickle.load(f)

def extract_bookmark_files(config_bookmark: dict) -> dict[str, str]:
    """
    Recursively walk the bookmark config tree.
    Returns {concept_name: file_path} for every leaf node.
    """
    files = {}
    for key, value in config_bookmark.items():
        if isinstance(value, str):
            files[key] = value
        elif isinstance(value, dict):
            files.update(extract_bookmark_files(value))
    return files