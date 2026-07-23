# -*- coding: utf-8 -*-
import re
import os
import hashlib
import requests
from io import BytesIO
from PIL import Image
from datetime import datetime
from app.schemas.crawler import CrawlNote
from app.schemas.cleaned_note import CleanedNote, CleanedComment, CleanedImage

class ContentCleaner:
    def __init__(self, image_output_dir: str = "data/processed/images"):
        self.version = "clean-v2.0"
        self.image_output_dir = image_output_dir
        os.makedirs(self.image_output_dir, exist_ok=True)
        
        # Regex patterns for noise reduction (Using Unicode escapes to prevent Windows encoding errors)
        # \u8bdd\u9898 = 话题
        self.re_topic = re.compile(r'#.*?\[\u8bdd\u9898\]#|#\S+')
        self.re_xhs_emoji = re.compile(r'\[.*?R\]')
        self.re_emoji = re.compile(r'[\U00010000-\U0010ffff]')
        self.re_url = re.compile(r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\(\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+')
        # \u52a0=加, \u5fae\u4fe1=微信, \u4e3b\u9875\u770b=主页看, \u4e3b\u9875\u94fe\u63a5=主页链接, \u79c1\u4fe1\u6211=私信我, \u4ee3\u8d2d=代购, \u907f\u96f7=避雷
        self.re_spam = re.compile(r'(\u52a0[vV]|\u5fae\u4fe1|\u4e3b\u9875\u770b|\u4e3b\u9875\u94fe\u63a5|\u79c1\u4fe1\u6211|\u4ee3\u8d2d|\u907f\u96f7)')

    def clean_text(self, text: str) -> str:
        """Purify text by removing noise, spam, and emojis."""
        if not text:
            return ""
            
        text = self.re_url.sub('', text)
        text = self.re_topic.sub(' ', text)
        text = self.re_xhs_emoji.sub('', text)
        text = self.re_emoji.sub('', text)
        text = self.re_spam.sub('', text)
        
        # Normalize whitespaces
        return re.sub(r'\s+', ' ', text).strip()

    def process_image(self, img_url: str, position: int) -> CleanedImage | None:
        """
        Download, compress, and validate image.
        Filters out low-res images (e.g., avatars or tracking pixels).
        """
        try:
            # 1. Download image with timeout
            resp = requests.get(img_url, timeout=5)
            if resp.status_code != 200:
                return None
                
            # 2. Open image with Pillow
            img = Image.open(BytesIO(resp.content))
            if img.mode != 'RGB':
                img = img.convert('RGB')
                
            # 3. Simple Recognition: Filter low resolution / avatars (e.g., < 200px)
            if img.width < 200 or img.height < 200:
                return None
                
            # 4. Compress & Resize (Max 800x800 for LLM efficiency)
            img.thumbnail((800, 800))
            
            # 5. Save locally using MD5 hash as filename
            img_hash = hashlib.md5(resp.content).hexdigest()
            filename = f"{img_hash}.jpg"
            filepath = os.path.join(self.image_output_dir, filename)
            
            img.save(filepath, "JPEG", quality=80)
            
            # Return cleaned image record
            return CleanedImage(position=position, url=filepath)
            
        except Exception as e:
            # If download fails, silently drop the image to avoid pipeline crash
            return None

    def process_note(self, raw_note: CrawlNote, seen_texts: set) -> CleanedNote | None:
        """
        Process a single raw note into a cleaned note for LLM.
        Applies Top-K truncation and deduplication.
        """
        # 1. Clean Title and Text
        clean_title = self.clean_text(raw_note.title)
        clean_text = self.clean_text(raw_note.text)
        
        if not clean_title and not clean_text:
            return None  # Drop empty notes
            
        # 2. Global Deduplication check
        combined_content = clean_title + clean_text
        if combined_content in seen_texts:
            return None
        seen_texts.add(combined_content)

        # 3. Process Images (Truncate to Top 3 to save LLM tokens & download time)
        cleaned_images = []
        for i, img in enumerate(raw_note.images[:3]):  # Max 3 images per note
            processed_img = self.process_image(img.url, img.position)
            if processed_img:
                cleaned_images.append(processed_img)

        # 4. Process & Filter Comments
        cleaned_comments = []
        for comment in raw_note.comments:
            c_text = self.clean_text(comment.text)
            # Filter short meaningless comments (e.g., "good", "up")
            if len(c_text) >= 4:
                is_author = (comment.author_id_hash == raw_note.author_id_hash)
                cleaned_comments.append(CleanedComment(
                    comment_id=comment.comment_id,
                    text=c_text,
                    likes=comment.likes or 0,
                    is_author=is_author
                ))
                
        # 5. Truncate Comments to Top-K (Sort by likes descending, keep Top 10)
        cleaned_comments.sort(key=lambda x: x.likes, reverse=True)
        top_k_comments = cleaned_comments[:10]

        # 6. Build and Return CleanedNote
        try:
            return CleanedNote(
                note_id=raw_note.note_id,
                url=raw_note.url,
                title=clean_title,
                text=clean_text,
                tags=raw_note.tags,
                publish_time=raw_note.publish_time,
                likes=raw_note.engagement.likes or 0,
                comments_count=raw_note.engagement.comments or 0,
                images=cleaned_images,
                comments=top_k_comments
            )
        except ValueError:
            # Pydantic validation failed
            return None
