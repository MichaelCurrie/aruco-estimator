import os
import shutil
import zipfile
from pathlib import Path
import pycolmap

def extract_from_zip(src_path:str, dst_path:str, zip_path:str):
    """
    Extract a file from a zip file
    """
    temp_extract_dir = 'temp_extract'
    os.makedirs(temp_extract_dir, exist_ok=True)

    with zipfile.ZipFile(zip_path, 'r') as zip_ref:
        zip_ref.extract(src_path, path=temp_extract_dir)

    os.makedirs(os.path.dirname(dst_path), exist_ok=True)
    extracted_file_path = os.path.join(temp_extract_dir, src_path)
    shutil.copy(extracted_file_path, dst_path)
    shutil.rmtree(temp_extract_dir)


def generate_colmap(image_path:str):
    # Given image_path, run COLMAP to generate
    #    /sparse/cameras.bin
    #    /sparse/images.bin
    #    /sparse/points3D.bin
    #    /fused.ply

    parent_path = Path(image_path).parent

    # Define paths
    database_path = parent_path / 'colmap.db'
    sparse_output = parent_path / 'sparse'
    dense_workspace = parent_path / 'dense'
    fused_output = parent_path / 'fused.ply'

    # Delete everything in the superfolder for images
    # because we're about to re-do the colmap reconstruction
    if sparse_output.is_dir():
        shutil.rmtree(sparse_output)

    if dense_workspace.is_dir():
        shutil.rmtree(dense_workspace)

    if database_path.is_file():
        os.remove(database_path)

    if fused_output.is_file():
        os.remove(fused_output)

    # Create necessary directories if they don't exist
    os.makedirs(sparse_output, exist_ok=True)
    os.makedirs(dense_workspace, exist_ok=True)

    # 1. Extract features and create the COLMAP database
    sift_options=pycolmap.SiftExtractionOptions()
    sift_options.num_threads=4
    sift_options.max_image_size=1024

    pycolmap.extract_features(
        database_path=database_path,
        image_path=image_path,
        camera_model="PINHOLE",  # or 'SIMPLE_RADIAL', etc.
        camera_mode=pycolmap.CameraMode.SINGLE,  # instead of single_camera=True
        reader_options=pycolmap.ImageReaderOptions(
            default_focal_length_factor=1.0  # keep other relevant settings
        ),
        sift_options=sift_options
    )

    # 2. Match features across images
    pycolmap.match_exhaustive(
        database_path=database_path,
        # If you want to pass SiftMatchingOptions:
        sift_options=pycolmap.SiftMatchingOptions(
            # other matching params here...
        ),
        # device=pycolmap.Device.cpu,
    )

    # 3. Run incremental mapping (sparse reconstruction)
    # This creates a subfolder (usually named "0") under /sparse containing:
    #   - cameras.bin
    #   - images.bin
    #   - points3D.bin
    sparse_models_dict = pycolmap.incremental_mapping(
        database_path=database_path,
        image_path=image_path,
        output_path=sparse_output,
        # mapper_options=mapper_options,
    )

    # (Optional) Move the files from the subfolder (e.g., /sparse/0) to /sparse directly:
    model_subfolder = os.path.join(sparse_output, '0')
    for file_name in ['cameras.bin', 'images.bin', 'points3D.bin']:
        src_file = os.path.join(model_subfolder, file_name)
        dst_file = os.path.join(sparse_output, file_name)
        if os.path.exists(src_file):
            os.replace(src_file, dst_file)

    # 4. Prepare for dense reconstruction by undistorting images using the sparse model
    pycolmap.undistort_images(
        image_path=image_path,
        input_path=sparse_output,
        output_path=dense_workspace,
        output_type='COLMAP'
    )

    if False:
        # WE CANNOT DO THIS PROPERLY SINCE WE NEED TO BUILD WITH CUDA
        # 5. Compute depth maps with patch-match stereo
        # (requires compilation with CUDA)
        # pycolmap.patch_match_stereo(workspace_path=dense_workspace)

        # 6. Fuse depth maps into a dense point cloud saved as fused.ply
        # pycolmap.stereo_fusion(workspace_path=dense_workspace, output_path=fused_output)
        pass
    else:
        # KLUDGE: Just grab the file from the ZIP for now
        extract_from_zip(src_path='door/fused.ply', dst_path=fused_output, zip_path=str(parent_path) + '.zip')
