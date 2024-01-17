import os

import pytest

from deeplabcut.pose_estimation_pytorch.modelzoo.utils import _get_config_model_paths


@pytest.mark.skip(reason="require-models")
@pytest.mark.parametrize(
    "project_name", ["superanimal_quadruped", "superanimal_topviewmouse"]
)
def test_get_config_model_paths(project_name):
    (
        model_config,
        project_config,
        pose_model_path,
        detector_model_path,
    ) = _get_config_model_paths(
        project_name,
        "hrnetw32",
        detector_type="fasterrcnn",
        weight_folder=None,
    )

    assert isinstance(model_config, dict)
    assert isinstance(project_config, dict)
    assert isinstance(pose_model_path, str)
    assert isinstance(detector_model_path, str)
    assert os.path.exists(pose_model_path)
    assert os.path.exists(detector_model_path)
