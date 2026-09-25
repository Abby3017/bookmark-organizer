from typing import Any

def tree_to_dict(tree: Any) -> dict:
    """Return a JSON-serializable view of the bookmark tree."""
    def node_to_dict(node: Any) -> dict:
        return {
            "name": node.name,
            "path": node.path,
            "file_path": node.file_path,
            "total_entries": node.total_entries,
            "sections": {
                name: {
                    "name": section.name,
                    "entry_count": section.entry_count,
                    "entries": [
                        {"title": entry.title, "url": entry.url, "tags": entry.tags}
                        for entry in section.entries
                    ],
                }
                for name, section in node.sections.items()
            },
            "children": {name: node_to_dict(child) for name, child in node.children.items()},
        }

    return node_to_dict(tree.root)

def candidate_sections(tree: Any) -> dict[str, dict[str, Any]]:
    """Flatten the tree into the labels Jev can choose from."""
    tree_data = tree_to_dict(tree)
    candidates: dict[str, dict[str, Any]] = {}

    def visit(node: dict[str, Any]) -> None:
        path = node["path"] or node["name"]
        for section_name, section in node.get("sections", {}).items():
            label = f"{path}#{section_name}"
            candidates[label] = {
                "path": path,
                "section": section_name,
                "entry_count": section.get("entry_count", 0),
                "example_titles": [
                    item["title"] for item in section.get("entries", [])[:5]
                ],
            }
        for child in node.get("children", {}).values():
            visit(child)

    visit(tree_data)
    return candidates