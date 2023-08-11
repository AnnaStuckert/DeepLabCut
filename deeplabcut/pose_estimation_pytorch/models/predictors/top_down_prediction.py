#
# DeepLabCut Toolbox (deeplabcut.org)
# © A. & M.W. Mathis Labs
# https://github.com/DeepLabCut/DeepLabCut
#
# Please see AUTHORS for contributors.
# https://github.com/DeepLabCut/DeepLabCut/blob/master/AUTHORS
#
# Licensed under GNU Lesser General Public License v3.0
#

import torch
from deeplabcut.pose_estimation_pytorch.models.predictors import (
    PREDICTORS,
    BasePredictor,
)


@PREDICTORS.register_module
class TopDownPredictor(BasePredictor):
    """Predictor for regressing keypoints in a Top Down fashion based on bbox predictions
    and regressed keypoints in cropped images.

    Args:
        format_bbox: Format of the bounding box prediction,
                     either 'xyxy' or 'coco'. Defaults to "xyxy".
    """

    def __init__(self, format_bbox: str = "xyxy"):
        super().__init__()

        self.format_bbox = format_bbox

    def _convert_bbox_to_coco(self, bboxes: torch.Tensor) -> torch.Tensor:
        """Convert bboxes in the format (x1, y1, x2, y2) to coco format (x, y, w, h)

        Args:
            bboxes: Bounding boxes of the shape (batch_size, max_num_animals, 4)

        Returns:
            coco_bboxes, shape (batch_size, max_num_animals, 4)
        """
        coco_bboxes = bboxes.clone()
        coco_bboxes[:, :, 2] -= coco_bboxes[:, :, 0]
        coco_bboxes[:, :, 3] -= coco_bboxes[:, :, 1]

        return coco_bboxes

    def forward(self, bboxes: torch.Tensor, keypoints_cropped: torch.Tensor) -> dict:
        """Computes keypoints coordinates in the original image given predicted bbox and predicted
        keypoints coordinates inside the bbox cropped image.

        Args:
            bboxes: Bounding boxes of the shape (batch_size, max_num_animals, 4)
            keypoints_cropped: Keypoints with the shape (batch_size, max_num_animals, num_joints, 3)

        Returns:
            A dictionary containing a "poses" key with a keypoints tensor of the shape:
            (batch_size, max_num_animals, num_joints, 3) as value.
        """
        if self.format_bbox != "coco":
            bboxes = self._convert_bbox_to_coco(bboxes)

        num_joints = keypoints_cropped.shape[2]
        new_kpts = keypoints_cropped.clone()

        x_corners = (bboxes[:, :, 0]).unsqueeze(2).expand(-1, -1, num_joints)
        y_corners = (bboxes[:, :, 1]).unsqueeze(2).expand(-1, -1, num_joints)
        # TODO hardcoded 256
        scales_x = (bboxes[:, :, 2] / 256).unsqueeze(2).expand(-1, -1, num_joints)
        scales_y = (bboxes[:, :, 3] / 256).unsqueeze(2).expand(-1, -1, num_joints)

        new_kpts[:, :, :, 0] = scales_x * new_kpts[:, :, :, 0] + x_corners
        new_kpts[:, :, :, 1] = scales_y * new_kpts[:, :, :, 1] + y_corners

        return {"poses": new_kpts}
