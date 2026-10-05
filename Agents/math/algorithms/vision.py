"""Pillar 4: pinhole projection, DLT homography, the 8-point algorithm, and Sobel."""

import numpy as np

from algorithms.errors import AlgorithmInputError

__all__ = [
    "compute_homography_dlt",
    "fundamental_matrix_8point",
    "pinhole_project",
    "sobel_gradients_2d",
]


def _scale_homogeneous(matrix: np.ndarray) -> np.ndarray:
    """Scale a 3x3 projective matrix without dividing by a near-zero corner."""
    norm = float(np.linalg.norm(matrix))
    if norm == 0.0:
        raise AlgorithmInputError("projective matrix vanished")
    anchor = float(matrix[2, 2])
    if abs(anchor) > 1e-8 * norm:
        return matrix / anchor
    return matrix / norm


def pinhole_project(
    points_xyz: np.ndarray,
    intrinsics: np.ndarray,
    rotation: np.ndarray,
    translation: np.ndarray,
) -> np.ndarray:
    """Project world points through ``x = K [R | t] X``.

    Args:
        points_xyz: World points of shape ``(n, 3)``.
        intrinsics: Camera matrix of shape ``(3, 3)``.
        rotation: Rotation of shape ``(3, 3)``.
        translation: Camera center offset of shape ``(3,)``.

    Returns:
        Pixel coordinates of shape ``(n, 2)``.
    """
    points = np.asarray(points_xyz, dtype=np.float64)
    matrix = np.asarray(intrinsics, dtype=np.float64)
    rot = np.asarray(rotation, dtype=np.float64)
    offset = np.asarray(translation, dtype=np.float64).reshape(-1)
    if points.ndim != 2 or points.shape[1] != 3 or points.shape[0] == 0:
        raise AlgorithmInputError("pinhole points must have shape (n, 3)")
    if matrix.shape != (3, 3) or rot.shape != (3, 3) or offset.shape != (3,):
        raise AlgorithmInputError("pinhole camera arguments have the wrong shape")
    camera = (rot @ points.T).T + offset
    if np.any(np.abs(camera[:, 2]) <= 1e-15):
        raise AlgorithmInputError("a point lies on the camera plane")
    projected = (matrix @ camera.T).T
    return projected[:, :2] / projected[:, 2:3]


def compute_homography_dlt(src_pts: np.ndarray, dst_pts: np.ndarray) -> np.ndarray:
    """Estimate a 3x3 homography from point pairs with the direct linear transform.

    Args:
        src_pts: Source points of shape ``(n, 2)``, ``n >= 4``.
        dst_pts: Destination points of the same shape.

    Returns:
        Homography normalized so ``H[2, 2] == 1`` when that entry is non-zero.
    """
    src = np.asarray(src_pts, dtype=np.float64)
    dst = np.asarray(dst_pts, dtype=np.float64)
    if src.shape != dst.shape or src.ndim != 2 or src.shape[1] != 2 or src.shape[0] < 4:
        raise AlgorithmInputError("DLT requires at least four (x, y) correspondences")
    rows = np.zeros((2 * src.shape[0], 9), dtype=np.float64)
    for index in range(src.shape[0]):
        x_coord, y_coord = src[index]
        u_coord, v_coord = dst[index]
        rows[2 * index] = [
            -x_coord,
            -y_coord,
            -1.0,
            0.0,
            0.0,
            0.0,
            u_coord * x_coord,
            u_coord * y_coord,
            u_coord,
        ]
        rows[2 * index + 1] = [
            0.0,
            0.0,
            0.0,
            -x_coord,
            -y_coord,
            -1.0,
            v_coord * x_coord,
            v_coord * y_coord,
            v_coord,
        ]
    vt = np.linalg.svd(rows)[-1]
    return _scale_homogeneous(vt[-1].reshape((3, 3)))


def _normalize_points(points: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    mean = np.mean(points, axis=0)
    distances = np.linalg.norm(points - mean, axis=1)
    mean_distance = float(np.mean(distances))
    if mean_distance == 0.0:
        raise AlgorithmInputError("8-point normalization received identical points")
    scale = np.sqrt(2.0) / mean_distance
    transform = np.array(
        [
            [scale, 0.0, -scale * mean[0]],
            [0.0, scale, -scale * mean[1]],
            [0.0, 0.0, 1.0],
        ],
        dtype=np.float64,
    )
    homogeneous = np.column_stack([points, np.ones(len(points))])
    normalized = (transform @ homogeneous.T).T
    return normalized[:, :2], transform


def fundamental_matrix_8point(pts1: np.ndarray, pts2: np.ndarray) -> np.ndarray:
    """Estimate a rank-2 fundamental matrix with the normalized 8-point algorithm.

    Args:
        pts1: Points in the first image, shape ``(n, 2)``, ``n >= 8``.
        pts2: Corresponding points in the second image.

    Returns:
        Fundamental matrix normalized by ``F[2, 2]`` when that entry is non-zero.
    """
    first = np.asarray(pts1, dtype=np.float64)
    second = np.asarray(pts2, dtype=np.float64)
    if first.shape != second.shape or first.ndim != 2 or first.shape[1] != 2 or first.shape[0] < 8:
        raise AlgorithmInputError("8-point algorithm requires at least eight correspondences")
    left, transform1 = _normalize_points(first)
    right, transform2 = _normalize_points(second)
    design = np.zeros((left.shape[0], 9), dtype=np.float64)
    for index in range(left.shape[0]):
        u1, v1 = left[index]
        u2, v2 = right[index]
        design[index] = [u2 * u1, u2 * v1, u2, v2 * u1, v2 * v1, v2, u1, v1, 1.0]
    vt = np.linalg.svd(design)[-1]
    fitted = vt[-1].reshape((3, 3))
    left_vectors, singular, right_vectors = np.linalg.svd(fitted)
    singular[2] = 0.0
    rank2 = left_vectors @ np.diag(singular) @ right_vectors
    return _scale_homogeneous(transform2.T @ rank2 @ transform1)


def sobel_gradients_2d(
    image: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return Sobel ``Gx``, ``Gy``, and the gradient magnitude of a 2-D image."""
    frame = np.asarray(image, dtype=np.float64)
    if frame.ndim != 2:
        raise AlgorithmInputError("Sobel input must be a 2-D image")
    kernel_x = np.array([[-1.0, 0.0, 1.0], [-2.0, 0.0, 2.0], [-1.0, 0.0, 1.0]])
    kernel_y = np.array([[-1.0, -2.0, -1.0], [0.0, 0.0, 0.0], [1.0, 2.0, 1.0]])
    height, width = frame.shape
    grad_x = np.zeros((height, width), dtype=np.float64)
    grad_y = np.zeros((height, width), dtype=np.float64)
    for row in range(1, height - 1):
        for col in range(1, width - 1):
            patch = frame[row - 1 : row + 2, col - 1 : col + 2]
            grad_x[row, col] = float(np.sum(patch * kernel_x))
            grad_y[row, col] = float(np.sum(patch * kernel_y))
    magnitude = np.sqrt(grad_x * grad_x + grad_y * grad_y)
    return grad_x, grad_y, magnitude
