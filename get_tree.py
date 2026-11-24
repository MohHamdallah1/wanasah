import os

# Directories that should not appear in the generated project tree.
IGNORE_DIRS = {
    "venv",
    "__pycache__",
    ".git",
    ".idea",
    "build",
    ".dart_tool",
    "android",
    "ios",
    "windows",
    "macos",
    "web",
    "linux",
    "node_modules",
    ".pub-cache",
    "assets",
    ".conda",
}

# Binary/runtime file extensions that are not useful in the project tree.
IGNORE_EXTENSIONS = {".dll", ".pdb", ".pyd", ".h"}

MAX_DEPTH = 5


def generate_tree(dir_path, prefix="", current_depth=1):
    if current_depth > MAX_DEPTH:
        return ""

    tree_str = ""

    try:
        items = sorted(os.listdir(dir_path))
    except PermissionError:
        return ""

    items = [
        item
        for item in items
        if not (
            os.path.isdir(os.path.join(dir_path, item))
            and item in IGNORE_DIRS
        )
    ]

    filtered_items = []
    for item in items:
        path = os.path.join(dir_path, item)

        if os.path.isfile(path):
            _, ext = os.path.splitext(item)
            if ext.lower() in IGNORE_EXTENSIONS:
                continue

        filtered_items.append(item)

    items = filtered_items

    for index, item in enumerate(items):
        if item in {"get_tree.py", "project_tree_clean.txt"}:
            continue

        path = os.path.join(dir_path, item)
        is_last = index == len(items) - 1

        # ASCII-only connectors avoid Windows editor/code-page problems.
        connector = "`-- " if is_last else "|-- "
        tree_str += f"{prefix}{connector}{item}\n"

        if os.path.isdir(path):
            extension = "    " if is_last else "|   "
            tree_str += generate_tree(
                path,
                prefix + extension,
                current_depth + 1,
            )

    return tree_str


if __name__ == "__main__":
    with open("project_tree_clean.txt", "w", encoding="utf-8", newline="\n") as file:
        file.write(generate_tree("."))

    print("Done. Project tree saved to project_tree_clean.txt")
