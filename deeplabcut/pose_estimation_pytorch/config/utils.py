"""Util functions to create pytorch pose configuration files"""
from __future__ import annotations

import copy
from pathlib import Path
from ruamel.yaml import YAML

from deeplabcut.utils import auxiliaryfunctions


def replace_default_values(
    config: dict | list,
    num_bodyparts: int | None = None,
    num_individuals: int | None = None,
    backbone_output_channels: int | None = None,
    **kwargs,
) -> dict:
    """Replaces placeholder values in a model configuration with their actual values.

    This method allows to create template PyTorch configurations for models with values
    such as "num_bodyparts", which are replaced with the number of bodyparts for a
    project when making its Pytorch configuration.

    This code can also do some basic arithmetic. You can write "num_bodyparts x 2" (or
    any factor other than 2) for location refinement channels, and the number of
    channels will be twice the number of bodyparts. You can write "num_bodyparts + 1"
    (such as for DEKR heatmaps, where a "center" bodypart is added).

    The three base placeholder values that can be computed are "num_bodyparts",
    "num_individuals" and "backbone_output_channels". You can add more through the
    keyword arguments (such as "paf_graph": list[tuple[int, int]] or
    "paf_edges_to_keep": list[int] for DLCRNet models).

    Args:
        config: the configuration in which to replace default values
        num_bodyparts: the number of bodyparts
        num_individuals: the number of individuals
        backbone_output_channels: the number of backbone output channels
        kwargs: other placeholder values to fill in

    Returns:
        the configuration with placeholder values replaced

    Raises:
        ValueError: if there is a placeholder value who's "updated" value was not
            given to the method
    """
    def get_updated_value(variable: str) -> int | list[int]:
        var_parts = variable.strip().split(" ")
        var_name = var_parts[0]
        if updated_values[var_name] is None:
            raise ValueError(
                f"Found {variable} in the configuration file, but there is no default "
                f"value for this variable."
            )

        if len(var_parts) == 1:
            return updated_values[var_name]
        elif len(var_parts) == 3:
            operator, factor = var_parts[1], var_parts[2]
            if not factor.isdigit():
                raise ValueError(f"F must be an integer in variable: {variable}")

            factor = int(factor)
            if operator == "+":
                return updated_values[var_name] + factor
            elif operator == "x":
                return updated_values[var_name] * factor
            else:
                raise ValueError(f"Unknown operator for variable: {variable}")

        raise ValueError(
            f"Found {variable} in the configuration file, but cannot parse it."
        )

    updated_values = {
        "num_bodyparts": num_bodyparts,
        "num_individuals": num_individuals,
        "backbone_output_channels": backbone_output_channels,
        **kwargs,
    }

    config = copy.deepcopy(config)
    if isinstance(config, dict):
        keys_to_update = list(config.keys())
    elif isinstance(config, list):
        keys_to_update = range(len(config))
    else:
        raise ValueError(f"Config to update must be dict or list, found {type(config)}")

    for k in keys_to_update:
        if isinstance(config[k], (list, dict)):
            config[k] = replace_default_values(
                config[k],
                num_bodyparts,
                num_individuals,
                backbone_output_channels,
                **kwargs,
            )
        elif (
            isinstance(config[k], str)
            and config[k].strip().split(" ")[0] in updated_values.keys()
        ):
            config[k] = get_updated_value(config[k])

    return config


def update_config(config: dict, updates: dict, copy_original: bool = True) -> dict:
    """Updates items in the configuration file

    The configuration dict should only be composed of primitive Python types
    (dict, list and values). This is the case when reading the file using
    `read_config_as_dict`.

    Args:
        config: the configuration dict to update
        updates: the updates to make to the configuration dict
        copy_original: whether to copy the original dict before updating it

    Returns:
        the updated dictionary
    """
    if copy_original:
        config = copy.deepcopy(config)

    for k, v in updates.items():
        if k in config and isinstance(config[k], dict) and isinstance(v, dict):
            config[k] = update_config(config[k], v, copy_original=False)
        else:
            config[k] = copy.deepcopy(v)
    return config


def load_config_dir_and_base_config() -> tuple[Path, dict]:
    """
    Returns:
        the Path to the folder containing the "configs" for PyTorch DeepLabCut
        the base configuration for all PyTorch DeepLabCut models
    """
    dlc_parent_path = Path(auxiliaryfunctions.get_deeplabcut_path())
    configs_dir = dlc_parent_path / "pose_estimation_pytorch" / "config"
    base_dir = configs_dir / "base"
    base_config = read_config_as_dict(base_dir / "base.yaml")
    return configs_dir, base_config


def load_backbones(configs_dir: Path) -> list[str]:
    """
    Args:
        configs_dir: the Path to the folder containing the "configs" for PyTorch
            DeepLabCut

    Returns:
        all backbones with default configurations that can be used
    """
    backbone_dir = configs_dir / "backbones"
    backbones = [p.stem for p in backbone_dir.iterdir() if p.suffix == ".yaml"]
    return backbones


def read_config_as_dict(config_path: str | Path) -> dict:
    """
    Args:
        config_path: the path to the configuration file to load

    Returns:
        The configuration file with pure Python classes
    """
    with open(config_path, "r") as f:
        cfg = YAML(typ='safe', pure=True).load(f)

    return cfg


def pretty_print_config(config: dict, indent: int = 0) -> None:
    """Prints a model configuration in a pretty and readable way

    Args:
        config: the config to print
        indent: the base indent on all keys
    """
    for k, v in config.items():
        if isinstance(v, dict):
            print(f"{indent * ' '}{k}:")
            pretty_print_config(v, indent + 2)
        else:
            print(f"{indent * ' '}{k}: {v}")
