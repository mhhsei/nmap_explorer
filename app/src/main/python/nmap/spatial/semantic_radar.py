import numpy as np
from typing import List, Dict, Any, Tuple
import threading
import logging

class SemanticRadar:
    """
    語意嗅覺雷達 (Semantic Olfactory Radar)
    Uses a highly efficient, edge-compatible embedding model to match vague user intents
    with physical POIs. Runs entirely locally on CPU.
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
        Loads the embedding model in a background thread so it doesn't block startup.
        BAAI/bge-small-zh-v1.5 is chosen for its SOTA Chinese retrieval performance and tiny size (~90MB).
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
        return np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b))

    def search_intent(self, intent_query: str, nearby_pois: List[Dict[str, Any]], top_k: int = 3, threshold: float = 0.5) -> List[Tuple[Dict[str, Any], float]]:
        """
        Matches an intent (e.g. "想上廁所", "口渴想喝冷飲") against nearby POIs.
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
