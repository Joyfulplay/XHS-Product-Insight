# -*- coding: utf-8 -*-
import json
import os
import time
from datetime import datetime
from app.schemas.crawler import CrawlDataset
from app.schemas.cleaned_note import CleanedDataset
from app.preprocess.cleaner import ContentCleaner

def run_pipeline():
    print("[INFO] Starting Batch ETL Pipeline (Extract, Transform, Load)...")
    start_time = time.time()

    # 1. 自动配置与创建所需目录
    raw_dir = os.path.join("data", "raw")
    processed_dir = os.path.join("data", "processed")
    image_output_dir = os.path.join(processed_dir, "images")

    os.makedirs(raw_dir, exist_ok=True)
    os.makedirs(processed_dir, exist_ok=True)
    os.makedirs(image_output_dir, exist_ok=True)

    # 2. 自动扫描 raw 目录下的所有 json 文件
    input_files = [f for f in os.listdir(raw_dir) if f.endswith('.json')]

    if not input_files:
        print(f"\n[WARNING] No .json files found in '{raw_dir}'.")
        print(f"[ACTION] Please put your crawler output files into the '{raw_dir}' folder and run again.")
        return

    print(f"[INFO] Found {len(input_files)} dataset(s) in '{raw_dir}'. Ready to process.")

    # 初始化清洗器
    cleaner = ContentCleaner(image_output_dir=image_output_dir)
    
    global_total_raw = 0
    global_total_cleaned = 0

    # 3. 遍历并批量处理每个文件
    for filename in input_files:
        input_filepath = os.path.join(raw_dir, filename)
        # 动态生成输出文件名：把 .json 替换成 _cleaned.jsonl
        output_filename = filename.replace('.json', '_cleaned.jsonl')
        output_filepath = os.path.join(processed_dir, output_filename)

        print(f"\n" + "-"*40)
        print(f"[PROCESSING] File: {filename}")
        print("-"*40)
        
        try:
            with open(input_filepath, "r", encoding="utf-8") as f:
                raw_json = json.load(f)
        except Exception as e:
            print(f"[ERROR] Failed to read {filename}: {e}")
            continue

        # == Pydantic Schema 严格校验 ==
        try:
            dataset = CrawlDataset.model_validate(raw_json)
            print("[SUCCESS] Schema validation passed.")
        except Exception as e:
            print(f"[ERROR] Validation failed for {filename}! Skipping this file. Error:\n{e}")
            continue

        seen_texts = set()
        cleaned_notes_list = []
        
        # == 清洗与图片处理 ==
        for note in dataset.notes:
            clean_note = cleaner.process_note(note, seen_texts)
            if clean_note:
                cleaned_notes_list.append(clean_note)

        # == 组装标准的 CleanedDataset 输出 ==
        query_context = dataset.input.resolved_query or dataset.input.value
        cleaned_dataset = CleanedDataset(
            query_context=query_context,
            cleaned_at=datetime.now().isoformat(),
            notes=cleaned_notes_list
        )

        # == 导出 JSONL 文件 ==
        with open(output_filepath, "w", encoding="utf-8") as f:
            # 写入元数据头
            meta_data = {
                "schema_version": cleaned_dataset.schema_version,
                "query_context": cleaned_dataset.query_context,
                "cleaned_at": cleaned_dataset.cleaned_at,
                "total_valid_notes": len(cleaned_dataset.notes)
            }
            f.write(json.dumps(meta_data, ensure_ascii=False) + "\n")
            
            # 逐行写入清洗好的笔记
            for note in cleaned_dataset.notes:
                f.write(note.model_dump_json(by_alias=True) + "\n")
        
        # 更新全局统计数据
        global_total_raw += len(dataset.notes)
        global_total_cleaned += len(cleaned_notes_list)
        
        print(f"[INFO] Exported {len(cleaned_notes_list)} clean notes to -> {output_filename}")

    elapsed_time = time.time() - start_time

    # 4. 全局执行总结报告
    print("\n" + "="*60)
    print(" " * 15 + "? BATCH PIPELINE SUMMARY")
    print("="*60)
    print(f" Datasets Processed      : {len(input_files)}")
    print(f" Total Raw Notes Scanned : {global_total_raw}")
    print(f" Total Valid Clean Notes : {global_total_cleaned}")
    print(f" Total Dropped Notes     : {global_total_raw - global_total_cleaned}")
    print(f" Output Directory        : {processed_dir}")
    print(f" Images Directory        : {image_output_dir}")
    print(f" Execution Time          : {elapsed_time:.2f} sec")
    print("="*60)

if __name__ == "__main__":
    run_pipeline()
