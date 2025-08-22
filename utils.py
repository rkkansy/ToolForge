"""Utility helpers (color detection, screenshots, timing helpers)."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import List, Sequence, Tuple
import numpy as np
from sklearn.cluster import DBSCAN

import pyautogui
from PIL import Image

BASE_DIR = Path(__file__).resolve().parent
SCRIPTS_DIR = BASE_DIR / "scripts"
PROGRAMS_DIR = BASE_DIR / "programs"

for _p in (SCRIPTS_DIR, PROGRAMS_DIR):
    _p.mkdir(exist_ok=True)


def screenshot_area(x: int, y: int, w: int, h: int, out: Path | str) -> None:
    """Capture rectangular region to *out* PNG."""
    region = (x, y, w, h)
    pyautogui.screenshot(region=region).save(out)


def find_color_clusters(
    img_path: Path | str,
    target: Tuple[int, int, int],
    *,
    offset: Tuple[int, int] = (0, 0),
    tolerance: int = 10,
    min_cluster_size: int = 5,
    max_distance: int = 20,
) -> List[Tuple[int, int]]:
    """
    Find clusters of pixels within `tolerance` of `target` color and return the
    mean (x, y) position of each cluster, **fast**.

    Args:
        img_path: Path to image (any PIL-readable format).
        target: RGB triple to match (r, g, b).
        offset: (dx, dy) added to returned coordinates.
        tolerance: Per-channel maximum absolute difference from `target`.
        min_cluster_size: Minimum #pixels for a valid cluster.
        max_distance: Maximum Euclidean distance (in pixels) between
                      neighbors for DBSCAN.
    Returns:
        List of (x, y) integer coordinates (cluster centroids).
    """
    # --- 1. Load & vectorize -------------------------------------------------
    img = Image.open(img_path).convert("RGB")
    arr = np.asarray(img, dtype=np.int16)          # shape (H, W, 3)

    # --- 2. Boolean mask of matching pixels ---------------------------------
    target_arr = np.array(target, dtype=np.int16)
    mask = np.all(np.abs(arr - target_arr) <= tolerance, axis=-1)

    # Short-circuit if nothing matches
    if not mask.any():
        return []

    # --- 3. Coordinates of matches (x, y) with optional offset --------------
    y_idx, x_idx = np.nonzero(mask)                # y first, then x
    coords = np.column_stack((x_idx, y_idx))       # shape (n, 2)
    coords += np.asarray(offset, dtype=np.int32)

    # --- 4. Density-based clustering (DBSCAN) -------------------------------
    db = DBSCAN(
        eps=max_distance,          # neighborhood radius
        min_samples=min_cluster_size,
        n_jobs=-1                  # use all CPU cores
    )
    labels = db.fit_predict(coords)

    # --- 5. Compute mean of each cluster ------------------------------------
    means: List[Tuple[int, int]] = []
    for lbl in np.unique(labels):
        if lbl == -1:              # DBSCAN noise label
            continue
        pts = coords[labels == lbl]
        mx, my = pts.mean(axis=0)
        means.append((int(mx), int(my)))

    return means

def find_color_clusters(
    img_path: Path | str,
    target: Tuple[int, int, int],
    *,
    offset: Tuple[int, int] = (0, 0),
    tolerance: int = 10,
    min_cluster_size: int = 5,
    max_distance: int = 5,
) -> List[Tuple[int, int]]:
    """
    Find clusters of pixels within tolerance of target color and return mean position of each cluster.
    
    Args:
        img_path: Path to the image file
        target: Target RGB color (r, g, b)
        offset: Offset to add to returned coordinates
        tolerance: Color tolerance for matching pixels
        min_cluster_size: Minimum number of pixels to consider a cluster
        max_distance: Maximum distance between pixels to be considered part of same cluster
    
    Returns:
        List of (x, y) coordinates representing the mean position of each cluster
    """
    with Image.open(img_path) as img:
        # Find all matching pixels
        matches: List[Tuple[int, int]] = []
        px = img.load()
        w, h = img.size
        for yy in range(h):
            for xx in range(w):
                r, g, b = px[xx, yy][:3]
                if all(abs(c - t) <= tolerance for c, t in zip((r, g, b), target)):
                    matches.append((offset[0] + xx, offset[1] + yy))
        
        if not matches:
            return []
        
        # Group pixels into clusters using distance-based clustering
        clusters = []
        used_pixels = set()
        
        for pixel in matches:
            if pixel in used_pixels:
                continue
                
            # Start a new cluster
            cluster = [pixel]
            used_pixels.add(pixel)
            
            # Find all pixels within max_distance of any pixel in this cluster
            changed = True
            while changed:
                changed = False
                for px1 in matches:
                    if px1 in used_pixels:
                        continue
                    
                    # Check if px1 is close to any pixel in current cluster
                    for px2 in cluster:
                        distance = ((px1[0] - px2[0]) ** 2 + (px1[1] - px2[1]) ** 2) ** 0.5
                        if distance <= max_distance:
                            cluster.append(px1)
                            used_pixels.add(px1)
                            changed = True
                            break
            
            # Only keep clusters that meet minimum size requirement
            if len(cluster) >= min_cluster_size:
                clusters.append(cluster)
        
        # Calculate mean position for each cluster
        cluster_means = []
        for cluster in clusters:
            if cluster:
                mx = sum(x for x, _ in cluster) / len(cluster)
                my = sum(y for _, y in cluster) / len(cluster)
                cluster_means.append((int(mx), int(my)))
        
        return cluster_means


def find_color_connected_clusters(
    img_path: Path | str,
    target: Tuple[int, int, int],
    *,
    offset: Tuple[int, int] = (0, 0),
    tolerance: int = 10,
    min_cluster_size: int = 5,
) -> List[Tuple[int, int]]:
    """
    Find clusters of pixels within tolerance of target color using connected components.
    Only pixels that are directly adjacent (neighboring) to other matching pixels form clusters.
    
    Args:
        img_path: Path to the image file
        target: Target RGB color (r, g, b)
        offset: Offset to add to returned coordinates
        tolerance: Color tolerance for matching pixels
        min_cluster_size: Minimum number of pixels to consider a cluster
    
    Returns:
        List of (x, y) coordinates representing the mean position of each cluster
    """
    with Image.open(img_path) as img:
        # Find all matching pixels
        matches: List[Tuple[int, int]] = []
        px = img.load()
        w, h = img.size
        
        # Create a 2D array to mark matching pixels
        match_grid = [[False for _ in range(w)] for _ in range(h)]
        
        for yy in range(h):
            for xx in range(w):
                r, g, b = px[xx, yy][:3]
                if all(abs(c - t) <= tolerance for c, t in zip((r, g, b), target)):
                    matches.append((xx, yy))
                    match_grid[yy][xx] = True
        
        if not matches:
            return []
        
        # Find connected components using flood fill
        clusters = []
        visited = [[False for _ in range(w)] for _ in range(h)]
        
        def flood_fill_iterative(start_x: int, start_y: int) -> List[Tuple[int, int]]:
            """Iterative flood fill to find all connected pixels of the same color."""
            if (start_x < 0 or start_x >= w or start_y < 0 or start_y >= h or 
                visited[start_y][start_x] or not match_grid[start_y][start_x]):
                return []
            
            cluster = []
            stack = [(start_x, start_y)]
            
            while stack:
                x, y = stack.pop()
                
                if (x < 0 or x >= w or y < 0 or y >= h or 
                    visited[y][x] or not match_grid[y][x]):
                    continue
                
                visited[y][x] = True
                cluster.append((x, y))
                
                # Add all 8 neighboring pixels to the stack
                for dx in [-1, 0, 1]:
                    for dy in [-1, 0, 1]:
                        if dx == 0 and dy == 0:
                            continue
                        stack.append((x + dx, y + dy))
            
            return cluster
        
        # Find all connected components
        for x, y in matches:
            if not visited[y][x]:
                cluster = flood_fill_iterative(x, y)
                if len(cluster) >= min_cluster_size:
                    clusters.append(cluster)
        
        # Calculate mean position for each cluster
        cluster_means = []
        for cluster in clusters:
            if cluster:
                # Apply offset to cluster coordinates
                offset_cluster = [(x + offset[0], y + offset[1]) for x, y in cluster]
                mx = sum(x for x, _ in offset_cluster) / len(offset_cluster)
                my = sum(y for _, y in offset_cluster) / len(offset_cluster)
                cluster_means.append((int(mx), int(my)))
        
        return cluster_means


def find_closest_cluster(clusters: List[Tuple[int, int]], player_pos: Tuple[int, int]) -> Tuple[int, int] | None:
    """
    Find the cluster closest to the player position.
    
    Args:
        clusters: List of cluster coordinates [(x, y), ...]
        player_pos: Player position (x, y)
    
    Returns:
        Coordinates of the closest cluster, or None if no clusters
    """
    if not clusters:
        return None
    
    closest_cluster = None
    min_distance = float('inf')
    
    for cluster in clusters:
        distance = ((cluster[0] - player_pos[0]) ** 2 + (cluster[1] - player_pos[1]) ** 2) ** 0.5
        if distance < min_distance:
            min_distance = distance
            closest_cluster = cluster
    
    return closest_cluster


def find_color_mean(
    img_path: Path | str,
    target: Tuple[int, int, int],
    *,
    offset: Tuple[int, int] = (0, 0),
    tolerance: int = 10,
) -> Tuple[int, int] | None:
    """Return mean (x,y) of all pixels within *tolerance* of *target*."""
    with Image.open(img_path) as img:
        matches: list[Tuple[int, int]] = []
        px = img.load()
        w, h = img.size
        for yy in range(h):
            for xx in range(w):
                r, g, b = px[xx, yy][:3]
                if all(abs(c - t) <= tolerance for c, t in zip((r, g, b), target)):
                    matches.append((offset[0] + xx, offset[1] + yy))
        if not matches:
            return None
        mx = sum(x for x, _ in matches) / len(matches)
        my = sum(y for _, y in matches) / len(matches)
        return int(mx), int(my)


def save_json(obj: object, path: Path | str) -> None:
    Path(path).write_text(json.dumps(obj, indent=4))


def load_json(path: Path | str):
    return json.loads(Path(path).read_text())