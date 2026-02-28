import os

# المجلدات المؤقتة والمزعجة اللي ما بدنا إياها
IGNORE_DIRS = {
    'venv', '__pycache__', '.git', '.idea', 'build', '.dart_tool', 
    'android', 'ios', 'windows', 'macos', 'web', 'linux', 
    'node_modules', '.pub-cache', 'assets', '.conda'
}

# الامتدادات اللي بدنا نستثنيها لأنها ملفات تشغيلية وما بتهم الذكاء الاصطناعي
IGNORE_EXTENSIONS = {'.dll', '.pdb', '.pyd', '.h'}

MAX_DEPTH = 4  # نزلنا للعمق الرابع بناءً على طلبك

def generate_tree(dir_path, prefix="", current_depth=1):
    if current_depth > MAX_DEPTH:
        return ""
        
    tree_str = ""
    try:
        items = sorted(os.listdir(dir_path))
    except PermissionError:
        return ""

    # فلترة المجلدات
    items = [f for f in items if not (os.path.isdir(os.path.join(dir_path, f)) and f in IGNORE_DIRS)]
    
    # فلترة الملفات حسب الامتداد
    filtered_items = []
    for f in items:
        if os.path.isfile(os.path.join(dir_path, f)):
            _, ext = os.path.splitext(f)
            if ext.lower() in IGNORE_EXTENSIONS:
                continue
        filtered_items.append(f)
        
    items = filtered_items
    
    for i, item in enumerate(items):
        if item in ["get_tree.py", "project_tree_clean.txt"]:
            continue
            
        path = os.path.join(dir_path, item)
        is_last = (i == len(items) - 1)
        connector = "└── " if is_last else "├── "
        tree_str += f"{prefix}{connector}{item}\n"
        
        if os.path.isdir(path):
            extension = "    " if is_last else "│   "
            tree_str += generate_tree(path, prefix + extension, current_depth + 1)
            
    return tree_str

if __name__ == "__main__":
    with open("project_tree_clean.txt", "w", encoding="utf-8") as f:
        f.write(generate_tree("."))
    print("تم! الشجرة النظيفة (لحد 4 مستويات ومفلترة من الملفات المزعجة) جاهزة في ملف project_tree_clean.txt")