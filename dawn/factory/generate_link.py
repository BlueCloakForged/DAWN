import os
import sys
import argparse
import shutil
from pathlib import Path

def generate_link(link_id: str, description: str):
    base_dir = Path(__file__).parent.parent
    template_dir = Path(__file__).parent / "templates" / "link_skeleton"
    target_dir = base_dir / "links" / link_id

    if target_dir.exists():
        print(f"Error: Link {link_id} already exists at {target_dir}")
        sys.exit(1)

    print(f"Creating new link: {link_id} at {target_dir}")
    target_dir.mkdir(parents=True, exist_ok=False)

    for template_file in template_dir.iterdir():
        if template_file.is_file():
            with open(template_file, "r") as f:
                content = f.read()

            # Simple template replacement
            content = content.replace("{{link_id}}", link_id)
            content = content.replace("{{description}}", description)

            with open(target_dir / template_file.name, "w") as f:
                f.write(content)

    print(f"Successfully generated link {link_id}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="DAWN Link Factory: Scaffolding a new link.")
    parser.add_argument("link_id", help="The ID for the link (e.g., quality.gates)")
    parser.add_argument("--description", "-d", default="A new DAWN link.", help="Short description of the link")
    
    args = parser.parse_args()
    generate_link(args.link_id, args.description)
