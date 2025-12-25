import json
import numpy as np
from typing import List, Dict, Any
from src.analysis.models import IssueCluster
from src.analysis.utils import generate_embedding
from src.utils.llm import LLMClientFactory

def cosine_similarity(v1: List[float], v2: List[float]) -> float:
    """Calculate cosine similarity between two vectors."""
    a = np.array(v1)
    b = np.array(v2)
    if np.all(a == 0) or np.all(b == 0):
        return 0.0
    return np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b))

class ClusteringEngine:
    """Groups similar issues and explains them using LLM."""
    
    def __init__(self, similarity_threshold: float = 0.70):
        self.similarity_threshold = similarity_threshold
        self.factory = LLMClientFactory()

    def cluster_issues(self, flattened_issues: List[Dict[str, Any]]) -> List[IssueCluster]:
        """Perform simple distance-based clustering on issues."""
        if not flattened_issues:
            return []

        # 1. Generate embeddings for all items
        for item in flattened_issues:
            if "embedding" not in item:
                item["embedding"] = generate_embedding(item["embedding_string"])

        clusters: List[IssueCluster] = []

        # 2. Assign items to clusters (greedy approach)
        for item in flattened_issues:
            assigned = False
            for cluster in clusters:
                # Check similarity against the mean embedding of the cluster
                sim = cosine_similarity(item["embedding"], cluster.metadata["mean_embedding"])
                if sim >= self.similarity_threshold:
                    self._add_to_cluster(cluster, item)
                    assigned = True
                    break
            
            if not assigned:
                # Create new cluster
                new_cluster = IssueCluster(
                    conversation_ids=[item["conversation_id"]],
                    metadata={
                        "mean_embedding": item["embedding"],
                        "issue_types": {item["issue_type"]},
                        "descriptions": [item["description"]]
                    }
                )
                clusters.append(new_cluster)

        # 3. Explain and score clusters using LLM
        for i, cluster in enumerate(clusters):
            print(f"DEBUG: Enriching cluster {i+1}/{len(clusters)} with LLM reasoning...")
            self._enrich_cluster(cluster)

        return clusters

    def _add_to_cluster(self, cluster: IssueCluster, item: Dict[str, Any]):
        """Helper to update cluster with new item."""
        cluster.conversation_ids.append(item["conversation_id"])
        cluster.metadata["descriptions"].append(item["description"])
        cluster.metadata["issue_types"].add(item["issue_type"])
        
        # Update mean embedding (running average)
        n = len(cluster.conversation_ids)
        prev_mean = np.array(cluster.metadata["mean_embedding"])
        curr_vec = np.array(item["embedding"])
        cluster.metadata["mean_embedding"] = ((prev_mean * (n - 1)) + curr_vec) / n

    def _enrich_cluster(self, cluster: IssueCluster):
        """Use LLM to explain the pattern and assign severity."""
        client = self.factory.get_client()
        if not client.api_key:
            cluster.explanation = "Mock: Found a pattern in conversation tools."
            cluster.severity = 5.0
            cluster.significance_score = len(cluster.conversation_ids) * 5.0
            cluster.label = "Potential Tool Error"
            return

        descriptions = "\n".join(list(set(cluster.metadata["descriptions"]))[:10])
        
        prompt = f"""Analyze this group of similar AI agent failures:
        
        Reported Issues:
        {descriptions}
        
        Provide a JSON response with:
        - "label": A short, punchy name for this pattern (max 5 words)
        - "explanation": What is the core technical cause? (1-2 sentences)
        - "severity": A score from 1.0 (low) to 10.0 (critical) based on the impact of this error.
        
        Response:"""

        try:
            response = client.chat.completions.create(
                model="gpt-4o",
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"}
            )
            data = json.loads(response.choices[0].message.content)
            
            cluster.label = data.get("label", "Unknown Pattern")
            cluster.explanation = data.get("explanation", "")
            cluster.severity = float(data.get("severity", 5.0))
            cluster.significance_score = len(cluster.conversation_ids) * cluster.severity
            
        except Exception as e:
            print(f"Error enriching cluster: {e}")
            cluster.label = "Analysis Failed"
            cluster.explanation = str(e)
