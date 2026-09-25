import os
import re

def rewrite_section_with_subsections(filepath: str, old_section: str, subsections: list[str], current_entries):
    """
    Rewrites a whole section distributing its old entries into new subsections 
    proposed by the agents.
    """
    # Complex section logic. For simplicity we'll just append it to 'Misc' 
    pass


def write_bookmark(base_dir: str, bookmark_entry, proposal):
    target_path = os.path.join(base_dir, proposal.path)
    
    if not target_path.endswith('.md'):
        target_path += '.md'
        
    os.makedirs(os.path.dirname(target_path), exist_ok=True)
    
    # Format entry
    content = bookmark_entry.to_markdown() + "\n\n"
    
    # Simple append logic for now
    if not os.path.exists(target_path):
        with open(target_path, 'w', encoding='utf-8') as f:
            f.write(f"# {os.path.basename(proposal.path).replace('.md','')}\n\n## {proposal.section}\n\n{content}")
    else:
        with open(target_path, 'r', encoding='utf-8') as f:
            text = f.read()
            
        if f"## {proposal.section}" in text:
            # Insert under existing section
            new_text = re.sub(
                r'(##\s+' + re.escape(proposal.section) + r'(?:\n+))',
                r'\1' + content,
                text,
                count=1
            )
            with open(target_path, 'w', encoding='utf-8') as f:
                f.write(new_text)
        else:
            with open(target_path, 'a', encoding='utf-8') as f:
                f.write(f"\n## {proposal.section}\n\n{content}")
