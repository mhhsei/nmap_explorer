"""
端側向量語意雷達 (Edge-AI Semantic Radar)

作用：
1. 採用輕量級高效中文向量模型 (BAAI/bge-small-zh-v1.5，僅約 90MB)，在背景執行緒中非同步載入，完全不阻塞主程式啟動。
2. 模糊需求語意匹配：將使用者的口語需求（例如：「肚子好餓想吃麵」、「想上廁所」、「口渴」）轉為 512 維語意向量。
3. 與周遭店家的名稱、設施標籤進行餘弦相似度 (Cosine Similarity) 比對，精準挑選出最適合去處。
"""
import numpy as np
from typing import List, Dict, Any, Tuple
import threading
import logging


class SemanticRadar:
    """
    語意嗅覺雷達 (Semantic Olfactory Radar) - 單例模式 (Singleton)
    """
    _instance = None
    _lock = threading.Lock()
    HAS_SENTENCE_TRANSFORMERS = False

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(SemanticRadar, cls).__new__(cls)
                cls._instance.model = None
                cls._instance.is_loading = False
            return cls._instance

    def initialize(self, model_name: str = "BAAI/bge-small-zh-v1.5"):
        """
        【在背景 Daemon 執行緒中非同步載入語意模型】
        """
        if self.model is not None or self.is_loading:
            return

        self.is_loading = True
        def load_model():
            try:
                logging.info(f"Loading Semantic Radar Model: {model_name}...")
                from sentence_transformers import SentenceTransformer
                SemanticRadar.HAS_SENTENCE_TRANSFORMERS = True
                self.model = SentenceTransformer(model_name)
                logging.info("Semantic Radar Model Loaded Successfully.")
            except Exception as e:
                SemanticRadar.HAS_SENTENCE_TRANSFORMERS = False
                logging.error(f"Failed to load sentence_transformers model: {e}")
            finally:
                self.is_loading = False
                
        threading.Thread(target=load_model, daemon=True).start()

    def cosine_similarity(self, a: np.ndarray, b: np.ndarray) -> float:
        """計算兩個向量的餘弦相似度 (Cosine Similarity)"""
        return np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b))

    def search_intent(self, intent_query: str, nearby_pois: List[Dict[str, Any]], top_k: int = 3, threshold: float = 0.5) -> List[Tuple[Dict[str, Any], float]]:
        """
        【以自然語言需求意圖搜尋周遭最匹配的店家】
        """

        if not SemanticRadar.HAS_SENTENCE_TRANSFORMERS or self.model is None:
            return []

        if not nearby_pois:
            return []

        # 1. Embed the user's intent query
        # For BAAI models, instructions are sometimes prepended for retrieval tasks.
        instruction = "為這個需求尋找最適合的商店或設施："
        query_embedding = self.model.encode(instruction + intent_query)

        # 2. Build semantic representations for all nearby POIs
        poi_texts = []
        for p in nearby_pois:
            name = p.get('name', '')
            cat = p.get('category', '')
            tags = p.get('tags', {})
            amenity = tags.get('amenity', '')
            shop = tags.get('shop', '')
            
            # Create a rich description for the POI
            desc = f"店名：{name}。類型：{cat}。"
            if amenity: desc += f"設施：{amenity}。"
            if shop: desc += f"商店：{shop}。"
            poi_texts.append(desc)

        # 3. Embed POIs
        poi_embeddings = self.model.encode(poi_texts)

        # 4. Calculate similarities
        results = []
        for i, poi in enumerate(nearby_pois):
            sim = self.cosine_similarity(query_embedding, poi_embeddings[i])
            if sim >= threshold:
                results.append((poi, float(sim)))

        # 5. Sort by similarity
        results.sort(key=lambda x: x[1], reverse=True)
        return results[:top_k]
