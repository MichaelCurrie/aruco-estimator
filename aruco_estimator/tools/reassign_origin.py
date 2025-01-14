# #!/usr/bin/env python
# # -*- coding: utf-8 -*-

import argparse
import logging
from pathlib import Path
import numpy as np
import open3d as o3d
from scipy.spatial.transform import Rotation
from colmap_wrapper.colmap import COLMAP, generate_colmap_sparse_pc
from aruco_estimator.localizers import ArucoLocalizer
from colmap_wrapper.colmap import write_points3D_text, write_images_text, write_cameras_text

def get_normalization_transform(aruco_corners_3d: np.ndarray) -> np.ndarray:
    """Calculate transformation matrix to normalize coordinates to ArUco marker plane."""
    if len(aruco_corners_3d) != 4:
        raise ValueError(f"Expected 4 ArUco corners, got {len(aruco_corners_3d)}")
    
    # Calculate ArUco center
    aruco_center = np.mean(aruco_corners_3d, axis=0)
    
    # Find the shortest and longest edges to determine marker orientation
    edges = []
    for i in range(4):
        next_i = (i + 1) % 4
        edge = aruco_corners_3d[next_i] - aruco_corners_3d[i]
        edges.append((np.linalg.norm(edge), edge, i))
    edges.sort(key=lambda x: x[0])  # Sort by edge length
    
    # Use shortest edge for y direction (typically marker height)
    # and its perpendicular for x direction (marker width)
    y_vec = edges[0][1]  # Shortest edge
    y_vec = y_vec / np.linalg.norm(y_vec)
    
    # Find the edge most perpendicular to y_vec
    perp_scores = []
    for _, edge, idx in edges[1:]:  # Skip shortest edge
        edge_norm = edge / np.linalg.norm(edge)
        # Score based on how close to perpendicular (dot product near 0)
        score = abs(np.dot(y_vec, edge_norm))
        perp_scores.append((score, edge_norm, idx))
    _, x_vec, _ = min(perp_scores, key=lambda x: x[0])
    
    # Calculate z-axis ensuring right-handed coordinate system
    z_vec = np.cross(x_vec, y_vec)
    z_vec = z_vec / np.linalg.norm(z_vec)
    
    # Ensure z-axis points upward
    if z_vec[2] < 0:
        z_vec = -z_vec
        x_vec = -x_vec  # Flip x to maintain right-handed system
    
    # Ensure y is exactly perpendicular
    y_vec = np.cross(z_vec, x_vec)
    y_vec = y_vec / np.linalg.norm(y_vec)
    
    # Create rotation matrix
    rotation = np.stack([x_vec, y_vec, z_vec], axis=0)
    
    # Create full transform
    transform = np.eye(4)
    transform[:3, :3] = rotation.T
    transform[:3, 3] = -rotation.T @ aruco_center
    
    return transform

def normalize_poses_and_points(project: COLMAP, transform: np.ndarray) -> None:
    """Apply normalization transform to both camera poses and 3D points using COLMAPProject"""
    # Transform camera poses
    for image in project.projects.images.values():
        new_pose = transform @ image.extrinsics
        image.qvec = Rotation.from_matrix(new_pose[:3, :3]).as_quat()[[3, 0, 1, 2]]  # w,x,y,z order
        image.tvec = new_pose[:3, 3]
        image.set_extrinsics(new_pose)
    
    # Transform 3D points
    rotation = transform[:3, :3]
    translation = transform[:3, 3]
    for point3D in project.projects.sparse.values():
        point3D.xyz = rotation @ point3D.xyz + translation
    return project

def save_normalized_data(project: COLMAP, output_path: Path) -> None:
    """Save normalized poses and points using COLMAP structure"""
    
    # Create normalized/sparse directory
    output_dir = output_path / "normalized" / "sparse"
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Use wrapper's built-in writing functions
    write_points3D_text(project.projects.sparse, output_dir / "points3D.txt")
    write_images_text(project.projects.images, output_dir / "images.txt")
    write_cameras_text(project.projects.cameras, output_dir / "cameras.txt")

def main():
    parser = argparse.ArgumentParser(description='Normalize COLMAP poses relative to ArUco marker')
    parser.add_argument('--colmap_project', type=str, required=True,
                       help='Path to COLMAP project containing images.txt and points3D.txt')
    parser.add_argument('--aruco_size', type=float, help='Size of the aruco marker in meter.', default=0.2)
    args = parser.parse_args()
    
    project_path = Path(args.colmap_project)
    logging.basicConfig(level=logging.INFO)
    
    # Initialize COLMAP project using wrapper
    logging.info("Initializing COLMAP project...")
    project = COLMAP(
        project_path=str(project_path),
    )
    
    # Get original point cloud
    original_points = generate_colmap_sparse_pc(project.projects.sparse)
    original_points.paint_uniform_color([0.7, 0.7, 0.7])  # Gray color
    
    # Get ArUco corners
    logging.info("Detecting ArUco markers and estimating scale...")
    aruco_localizer = ArucoLocalizer(
        photogrammetry_software=project,
        aruco_size=args.aruco_size,
    )
    aruco_distance, aruco_corners_3d = aruco_localizer.run()
    logging.info(f"ArUco 3d points: {aruco_corners_3d}")
    logging.info(f"ArUco marker distance: {aruco_distance}")
    
    # Calculate normalization transform
    transform = get_normalization_transform(aruco_corners_3d)
    
    # Apply normalization
    logging.info("Normalizing poses and 3D points...")
    project = normalize_poses_and_points(project, transform)
    
    # Get transformed point cloud
    transformed_points = generate_colmap_sparse_pc(project.projects.sparse)
    # transformed_points.paint_uniform_color([0.7, 0.7, 1.0])  # Light blue color
    
    # Visualize the transformation
    logging.info("Visualizing coordinate transformation...")
    
    # Create coordinate frames
    original_frame = o3d.geometry.TriangleMesh.create_coordinate_frame(size=2.0)
    transformed_frame = o3d.geometry.TriangleMesh.create_coordinate_frame(size=1)
    transformed_frame.transform(transform)
    
    # Transform ArUco corners to new coordinate system
    transformed_corners = np.array([
        transform[:3, :3] @ corner + transform[:3, 3] 
        for corner in aruco_corners_3d
    ])
    
    # Create ArUco marker visualization (transformed)
    aruco_lines = o3d.geometry.LineSet()
    aruco_lines.points = o3d.utility.Vector3dVector(transformed_corners)
    aruco_lines.lines = o3d.utility.Vector2iVector([[0,1], [1,2], [2,3], [3,0]])
    aruco_lines.colors = o3d.utility.Vector3dVector([[0,1,1] for _ in range(4)])  # Cyan edges
    
    # Create point cloud for ArUco corners (transformed)
    corner_points = o3d.geometry.PointCloud()
    corner_points.points = o3d.utility.Vector3dVector(transformed_corners)
    corner_points.paint_uniform_color([1,0,0])  # Red points
    
    # Log transformed corners for verification
    logging.info("Transformed ArUco corners:")
    for i, corner in enumerate(transformed_corners):
        logging.info(f"Corner {i}: {corner}")
    
    # Visualize
    o3d.visualization.draw_geometries([
        original_frame,      # Original coordinate system
        transformed_frame,   # Transformed coordinate system
        aruco_lines,        # ArUco marker edges
        corner_points,      # ArUco corner points
        original_points,     # Original project points (gray)
        transformed_points   # Transformed project points (light blue)
    ])
    
    # Save normalized data
    logging.info("Saving normalized data...")
    save_normalized_data(project, project_path)
    
    logging.info("Done! Normalized data saved to normalized/sparse/")

if __name__ == '__main__':
    main()
