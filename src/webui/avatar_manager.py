def read_avatar_sections(file_path):
    sections = {
        'task': '',
        'role': '',
        'appearance': '',
        'experience': '',
        'personality': '',
        'classic_lines': '',
        'preferences': '',
        'notes': ''
    }
    
    current_section = None
    content = []
    
    try:
        with open(file_path, 'r', encoding='utf-8') as file:
            lines = file.readlines()
            
            for line in lines:
                line = line.strip()
                if line.startswith('# '):
                    # 如果之前有section，保存其内容
                    if current_section and content:
                        sections[current_section.lower()] = '\n'.join(content).strip()
                        content = []
                    # 获取新的section名称
                    current_section = line[2:].lower()
                elif current_section and line:
                    content.append(line)
            
            # 保存最后一个section的内容
            if current_section and content:
                sections[current_section.lower()] = '\n'.join(content).strip()
                
        return sections
    except Exception as e:
        print(f"Error reading avatar file: {e}")
        return sections 