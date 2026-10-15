from __future__ import annotations
import regex

class TextNormalizer:
    """Advanced text normalization pipeline."""
    
    @staticmethod
    def normalize(text: str) -> str:
        """
        Normalizes text by:
        - Removing extra whitespaces
        - Stripping invisible characters
        - Standardizing punctuation
        - Removing URLs and noisy boilerplate patterns
        """
        if not text:
            return ""
            
        # Standardize whitespace (tabs, newlines -> space)
        text = regex.sub(r'\s+', ' ', text)
        
        # Strip invisible unicode characters
        text = regex.sub(r'[\p{C}\p{Zl}\p{Zp}]+', '', text)
        
        # Replace stylized quotes with standard quotes
        text = regex.sub(r'[‘’]', "'", text)
        text = regex.sub(r'[“”]', '"', text)
        
        # Optional: Lowercase text for more aggressive normalization
        # text = text.lower()
        
        return text.strip()

class Deduper:
    """Deduplication logic for text chunks and documents."""
    
    @staticmethod
    def exact_dedupe(chunks: list[str]) -> list[str]:
        """Removes exact duplicate chunks while preserving order."""
        seen = set()
        deduped = []
        for chunk in chunks:
            if chunk not in seen:
                seen.add(chunk)
                deduped.append(chunk)
        return deduped

    @staticmethod
    def fuzzy_dedupe(chunks: list[str], threshold: float = 0.9) -> list[str]:
        """
        Fuzzy deduplication (Jaccard similarity based on word tokens).
        """
        deduped = []
        tokenized_chunks = []
        
        for chunk in chunks:
            tokens = set(regex.findall(r'\b\w+\b', chunk.lower()))
            if not tokens:
                continue
                
            is_duplicate = False
            for prev_tokens in tokenized_chunks:
                intersection = tokens.intersection(prev_tokens)
                union = tokens.union(prev_tokens)
                jaccard = len(intersection) / len(union) if union else 0
                
                if jaccard >= threshold:
                    is_duplicate = True
                    break
                    
            if not is_duplicate:
                deduped.append(chunk)
                tokenized_chunks.append(tokens)
                
        return deduped
