# -*- coding: utf-8 -*-
import json
import os
import jieba
import matplotlib.pyplot as plt
from wordcloud import WordCloud
from collections import Counter

def generate_eda_reports():
    print("[INFO] Starting Exploratory Data Analysis (EDA)...")
    
    # 1. 动态获取所有文件
    raw_dir = os.path.join("data", "raw")
    processed_dir = os.path.join("data", "processed")
    output_dir = os.path.join("data", "processed", "eda_charts")
    os.makedirs(output_dir, exist_ok=True)
    
    # 寻找所有的清洗后数据文件
    if not os.path.exists(processed_dir):
        print(f"[ERROR] Directory {processed_dir} does not exist. Run cleaner first!")
        return
        
    processed_files = [f for f in os.listdir(processed_dir) if f.endswith('.jsonl')]
    if not processed_files:
        print(f"[ERROR] No cleaned .jsonl files found in {processed_dir}. Run cleaner first!")
        return

    # ========================================================
    # Task 3: Data Sample Overview (Authentic Calculation)
    # ========================================================
    print("[INFO] Calculating exact numbers for Task 3 (Data Overview)...")
    
    raw_notes_count = 0
    raw_comments_count = 0
    
    # 统计所有 Raw Data 原始抓取量
    if os.path.exists(raw_dir):
        raw_files = [f for f in os.listdir(raw_dir) if f.endswith('.json')]
        for f in raw_files:
            with open(os.path.join(raw_dir, f), "r", encoding="utf-8", errors="ignore") as file:
                try:
                    raw_data = json.load(file)
                    notes = raw_data.get("notes", [])
                    raw_notes_count += len(notes)
                    for n in notes:
                        raw_comments_count += len(n.get("comments", []))
                except:
                    pass

    # 统计所有 Clean Data 清洗后有效量
    clean_notes_count = 0
    clean_comments_count = 0
    all_clean_texts = []
    
    for f in processed_files:
        filepath = os.path.join(processed_dir, f)
        with open(filepath, "r", encoding="utf-8", errors="ignore") as file:
            lines = file.readlines()
            for line in lines[1:]: # 跳过第一行的 meta data
                try:
                    note = json.loads(line)
                    clean_notes_count += 1
                    all_clean_texts.append(note.get("title", "") + " " + note.get("text", ""))
                    
                    comments = note.get("comments", [])
                    clean_comments_count += len(comments)
                    for c in comments:
                        all_clean_texts.append(c.get("text", ""))
                except:
                    pass

    print("[INFO] Generating Data Overview Chart...")
    
    labels = ['Notes', 'Comments']
    raw_data = [raw_notes_count, raw_comments_count]
    clean_data = [clean_notes_count, clean_comments_count]

    x = range(len(labels))
    width = 0.35

    fig, ax = plt.subplots(figsize=(8, 6))
    ax.bar([i - width/2 for i in x], raw_data, width, label='Raw (Crawled)', color='#FF9999')
    ax.bar([i + width/2 for i in x], clean_data, width, label='Clean (Valid)', color='#66B2FF')

    ax.set_ylabel('Count')
    ax.set_title('Data Preprocessing & Filtering Funnel Overview')
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.legend()
    
    # 在柱子上标出数字
    for i, v in enumerate(raw_data):
        ax.text(i - width/2, v + 1, str(v), ha='center', va='bottom', fontweight='bold')
    for i, v in enumerate(clean_data):
        ax.text(i + width/2, v + 1, str(v), ha='center', va='bottom', fontweight='bold')

    overview_path = os.path.join(output_dir, "data_overview.png")
    plt.savefig(overview_path, dpi=300, bbox_inches='tight')
    plt.close()
    print(f"[SUCCESS] Saved Overview Chart to {overview_path}")

    # ========================================================
    # Task 5: High-Quality Word Cloud
    # ========================================================
    print("[INFO] Generating Word Cloud...")
    
    # 停用词（使用 Unicode 以防止 Windows 编码报错）
    stop_words = {
        "\u771f\u7684", "\u611f\u89c9", "\u4e0d\u9519", "\u53ef\u4ee5", "\u5c31\u662f", 
        "\u8fd8\u662f", "\u8fd9\u4e2a", "\u90a3\u4e2a", "\u600e\u4e48", "\u8033\u673a", 
        "\u964d\u566a", "\u7d22\u5c3c", "\u4e70", "\u5356", "\u7684", "\u4e86", "\u5728", 
        "\u662f", "\u6211", "\u6709", "\u548c", "\u5c31", "\u4e0d", "\u4eba", "\u90fd", 
        "\u4e00", "\u4e00\u4e2a", "\u4e0a", "\u4e5f", "\u5f88", "\u5230", "\u8bf4", 
        "\u8981", "\u53bb", "\u4f60", "\u4f1a", "\u7740", "\u6ca1\u6709", "\u770b", 
        "\u597d", "\u81ea\u5df1", "\u8fd9", "\u554a"
    }

    full_text = " ".join(all_clean_texts)
    words = jieba.cut(full_text)
    
    filtered_words = [w for w in words if w not in stop_words and len(w) > 1]
    word_freq = Counter(filtered_words)

    font_path = 'simhei.ttf' if os.name == 'nt' else None
    
    try:
        wc = WordCloud(
            font_path=font_path,
            width=1000, height=600,
            background_color='white',
            max_words=100,
            colormap='viridis'
        )
        wc.generate_from_frequencies(word_freq)

        plt.figure(figsize=(10, 6))
        plt.imshow(wc, interpolation='bilinear')
        plt.axis('off')
        
        wc_path = os.path.join(output_dir, "word_cloud.png")
        plt.savefig(wc_path, dpi=300, bbox_inches='tight')
        plt.close()
        print(f"[SUCCESS] Saved Word Cloud to {wc_path}")
    except Exception as e:
        print(f"[WARNING] WordCloud generation skipped due to font issue. Error: {e}")

    # 打印最终战报
    print("\n" + "="*50)
    print(" ? TASK 3: DATA SAMPLE OVERVIEW SUMMARY")
    print("="*50)
    print(f" Raw Notes Crawled      : {raw_notes_count}")
    print(f" Raw Comments Crawled   : {raw_comments_count}")
    print("-" * 50)
    print(f" Clean Notes Kept       : {clean_notes_count}")
    print(f" Clean Comments Kept    : {clean_comments_count}")
    print("-" * 50)
    print(f" Notes Deduplicated     : {raw_notes_count - clean_notes_count}")
    print(f" Comments Filtered      : {raw_comments_count - clean_comments_count}")
    print("="*50)

if __name__ == "__main__":
    generate_eda_reports()
