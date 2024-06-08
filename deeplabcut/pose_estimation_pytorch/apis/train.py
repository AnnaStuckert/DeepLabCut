#
# DeepLabCut Toolbox (deeplabcut.org)
# © A. & M.W. Mathis Labs
# https://github.com/DeepLabCut/DeepLabCut
#
# Please see AUTHORS for contributors.
# https://github.com/DeepLabCut/DeepLabCut/blob/main/AUTHORS
#
# Licensed under GNU Lesser General Public License v3.0
#
from __future__ import annotations

import argparse
import copy
import logging
from pathlib import Path

import albumentations as A
from torch.utils.data import DataLoader

import deeplabcut.pose_estimation_pytorch.config as torch_config
import deeplabcut.pose_estimation_pytorch.modelzoo.utils as modelzoo_utils
import deeplabcut.pose_estimation_pytorch.utils as utils
from deeplabcut.core.weight_init import WeightInitialization
from deeplabcut.pose_estimation_pytorch.data import (
    build_transforms,
    COCOLoader,
    DLCLoader,
    Loader,
)
from deeplabcut.pose_estimation_pytorch.data.collate import COLLATE_FUNCTIONS
from deeplabcut.pose_estimation_pytorch.models import DETECTORS, PoseModel
from deeplabcut.pose_estimation_pytorch.modelzoo.memory_replay import (
    prepare_memory_replay,
)
from deeplabcut.pose_estimation_pytorch.runners import build_training_runner
from deeplabcut.pose_estimation_pytorch.runners.logger import (
    destroy_file_logging,
    LOGGER,
    setup_file_logging,
)
from deeplabcut.pose_estimation_pytorch.task import Task


def train(
    loader: Loader,
    run_config: dict,
    task: Task,
    device: str | None = "cpu",
    logger_config: dict | None = None,
    snapshot_path: str | None = None,
    transform: A.BaseCompose | None = None,
    inference_transform: A.BaseCompose | None = None,
    max_snapshots_to_keep: int | None = None,
) -> None:
    """Builds a model from a configuration and fits it to a dataset

    Args:
        loader: the loader containing the data to train on/validate with
        run_config: the model and run configuration
        task: the task to train the model for
        device: the torch device to train on (such as "cpu", "cuda", "mps")
        logger_config: the configuration of a logger to use
        snapshot_path: if continuing to train from a snapshot, the path containing the
            weights to load
        transform: if defined, overwrites the transform defined in the model config
        inference_transform: if defined, overwrites the inference transform defined in
            the model config
        max_snapshots_to_keep: the maximum number of snapshots to store for each model
    """
    weight_init = None
    pretrained = True
    if weight_init_cfg := run_config["train_settings"].get("weight_init"):
        weight_init = WeightInitialization.from_dict(weight_init_cfg)
        pretrained = False

    if task == Task.DETECT:
        model = DETECTORS.build(
            run_config["model"],
            weight_init=weight_init,
            pretrained=pretrained,
        )
    else:
        model = PoseModel.build(
            run_config["model"],
            weight_init=weight_init,
            pretrained_backbone=pretrained,
        )

    if max_snapshots_to_keep is not None:
        run_config["runner"]["snapshots"]["max_snapshots"] = max_snapshots_to_keep

    logger = None
    if logger_config is not None:
        logger = LOGGER.build(dict(**logger_config, model=model))
        logger.log_config(run_config)

    if device is None:
        device = utils.resolve_device(run_config)

    if device == "mps" and task == Task.DETECT:
        device = "cpu"  # FIXME: Cannot train detectors on MPS

    model.to(device)  # Move model before giving its parameters to the optimizer
    runner = build_training_runner(
        runner_config=run_config["runner"],
        model_folder=loader.model_folder,
        task=task,
        model=model,
        device=device,
        snapshot_path=snapshot_path,
        logger=logger,
    )

    if transform is None:
        transform = build_transforms(run_config["data"]["train"])
    if inference_transform is None:
        inference_transform = build_transforms(run_config["data"]["inference"])

    logging.info("Data Transforms:")
    logging.info(f"  Training:   {transform}")
    logging.info(f"  Validation: {inference_transform}")

    train_dataset = loader.create_dataset(transform=transform, mode="train", task=task)
    valid_dataset = loader.create_dataset(
        transform=inference_transform, mode="test", task=task
    )
    logging.info(
        f"Using {len(train_dataset)} images to train {task} and {len(valid_dataset)}"
        f" for testing"
    )

    collate_fn = None
    if collate_fn_cfg := run_config["data"]["train"].get("collate"):
        collate_fn = COLLATE_FUNCTIONS.build(collate_fn_cfg)
        logging.info(f"Using custom collate function: {collate_fn_cfg}")

    batch_size = run_config["train_settings"]["batch_size"]
    num_workers = run_config["train_settings"]["dataloader_workers"]
    pin_memory = run_config["train_settings"]["dataloader_pin_memory"]
    train_dataloader = DataLoader(
        train_dataset,
        batch_size=batch_size,
        shuffle=True,
        collate_fn=collate_fn,
        num_workers=num_workers,
        pin_memory=pin_memory,
    )
    valid_dataloader = DataLoader(
        valid_dataset,
        batch_size=1,
        shuffle=False,
        num_workers=num_workers,
        pin_memory=pin_memory,
    )
    runner.fit(
        train_dataloader,
        valid_dataloader,
        epochs=run_config["train_settings"]["epochs"],
        display_iters=run_config["train_settings"]["display_iters"],
    )


def train_network(
    config: str,
    shuffle: int = 1,
    trainingsetindex: int = 0,
    modelprefix: str = "",
    device: str | None = None,
    snapshot_path: str | None = None,
    detector_path: str | None = None,
    batch_size: int | None = None,
    epochs: int | None = None,
    save_epochs: int | None = None,
    display_iters: int | None = None,
    max_snapshots_to_keep: int | None = None,
    pose_threshold: float | None = 0.1,
    **kwargs,
) -> None:
    """Trains a network for a project

    Args:
        config : path to the yaml config file of the project
        shuffle : index of the shuffle we want to train on
        trainingsetindex : training set index
        modelprefix: directory containing the deeplabcut configuration files to use
            to train the network (and where snapshots will be saved). By default, they
             are assumed to exist in the project folder.
        device: the torch device to train on (such as "cpu", "cuda", "mps")
        snapshot_path: if resuming training, the snapshot from which to resume
        detector_path: if resuming training of a top-down model, used to specify the
            detector snapshot from which to resume
        batch_size: overrides the batch size to train with
        epochs: overrides the maximum number of epochs to train the model for
        save_epochs: overrides the number of epochs between each snapshot save
        display_iters: overrides the number of iterations between each log of the loss
            within an epoch
        max_snapshots_to_keep: the maximum number of snapshots to save for each model
        pose_threshold: used for memory-replay. pseudo predictions that are below this are discarded for memory-replay
        **kwargs : could be any entry of the pytorch_config dictionary. Examples are
            to see the full list see the pytorch_cfg.yaml file in your project folder
    """
    loader = DLCLoader(
        config=config,
        shuffle=shuffle,
        trainset_index=trainingsetindex,
        modelprefix=modelprefix,
    )

    if weight_init_cfg := loader.model_cfg["train_settings"].get("weight_init"):
        weight_init = WeightInitialization.from_dict(weight_init_cfg)

        if weight_init.memory_replay:
            dataset_params = loader.get_dataset_parameters()
            backbone_name = loader.model_cfg["model"]["backbone"]["model_name"]
            model_name = modelzoo_utils.get_pose_model_type(backbone_name)
            # at some point train_network should support a different train_file passing so memory replay can also take the same train file
            superanimal_model_config = prepare_memory_replay(
                loader.project_path,
                shuffle,
                weight_init.dataset,
                model_name,
                device,
                train_file = "train.json",
                max_individuals=dataset_params.max_num_animals,
                pose_threshold = pose_threshold
            )
            loader = COCOLoader(
                project_root=Path(loader.model_folder).parent / "memory_replay",
                model_config_path=loader.model_config_path,
                train_json_filename = "memory_replay_train.json"
            )

    if batch_size is not None:
        loader.model_cfg["train_settings"]["batch_size"] = batch_size
    if epochs is not None:
        loader.model_cfg["train_settings"]["epochs"] = epochs
    if save_epochs is not None:
        loader.model_cfg["runner"]["snapshots"]["save_epochs"] = save_epochs
    if display_iters is not None:
        loader.model_cfg["train_settings"]["display_iters"] = display_iters

    loader.update_model_cfg(kwargs)
    setup_file_logging(loader.model_folder / "train.txt")

    logging.info("Training with configuration:")
    torch_config.pretty_print(loader.model_cfg, print_fn=logging.info)

    # fix seed for reproducibility
    utils.fix_seeds(loader.model_cfg["train_settings"]["seed"])

    # get the pose task
    pose_task = Task(loader.model_cfg.get("method", "bu"))
    if (
        pose_task == Task.TOP_DOWN
        and loader.model_cfg["detector"]["train_settings"]["epochs"] > 0
    ):
        logger_config = None
        if loader.model_cfg.get("logger"):
            logger_config = copy.deepcopy(loader.model_cfg["logger"])
            logger_config["run_name"] += "-detector"

        detector_run_config = loader.model_cfg["detector"]
        detector_run_config["device"] = loader.model_cfg["device"]
        detector_run_config["train_settings"]["weight_init"] = loader.model_cfg[
            "train_settings"
        ].get("weight_init")
        train(
            loader=loader,
            run_config=detector_run_config,
            task=Task.DETECT,
            device=device,
            logger_config=logger_config,
            snapshot_path=detector_path,
            max_snapshots_to_keep=max_snapshots_to_keep,
        )

    train(
        loader=loader,
        run_config=loader.model_cfg,
        task=pose_task,
        device=device,
        logger_config=loader.model_cfg.get("logger"),
        snapshot_path=snapshot_path,
        max_snapshots_to_keep=max_snapshots_to_keep,
    )

    destroy_file_logging()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config-path", type=str)
    parser.add_argument("--shuffle", type=int, default=1)
    parser.add_argument("--train-ind", type=int, default=0)
    parser.add_argument("--modelprefix", type=str, default="")
    args = parser.parse_args()
    train_network(
        config=args.config_path,
        shuffle=args.shuffle,
        trainingsetindex=args.train_ind,
        modelprefix=args.modelprefix,
    )
