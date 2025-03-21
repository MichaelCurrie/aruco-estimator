import os
import logging
from pathlib import Path

from aruco_estimator.localizers import ArucoLocalizer
from aruco_estimator.visualization import ArucoVisualization
from aruco_estimator.tools.downloader import Dataset

# This patches pycolmap to fix a bug in colmap_wrapper
import aruco_estimator.patch_colmap

from colmap_wrapper.colmap import COLMAP


def main():
    dataset = Dataset()

    # Download example dataset. Door dataset is roughly 200 MB
    DOOR_TAG_ID = 7
    dataset.download_door_dataset()

    # Load Colmap project folder
    project = COLMAP(project_path=dataset.dataset_path, image_resize=0.4)

    # Init & run pose estimation of corners in 3D & estimate mean L2 distance between the four aruco corners
    aruco_localizer = ArucoLocalizer(
        photogrammetry_software=project, aruco_size=dataset.scale, target_id=DOOR_TAG_ID
    )
    aruco_distance, aruco_corners_3d = aruco_localizer.run()
    logging.info("Size of the unscaled aruco markers: ", aruco_distance)

    # Calculate scaling factor, apply it to the scene and save scaled point cloud
    dense, scale_factor = aruco_localizer.apply()
    logging.info("Point cloud and poses are scaled by: ", scale_factor)
    logging.info(
        "Size of the scaled (true to scale) aruco markers in meters: ",
        aruco_distance * scale_factor,
    )

    # Visualization of the scene and rays
    vis = ArucoVisualization(aruco_colmap=aruco_localizer)
    vis.visualization(frustum_scale=0.7, point_size=0.1)

    # Write Data
    aruco_localizer.write_data()


if __name__ == "__main__":
    main()
