import argparse

import numpy as np
import torch

from datamodule.shrec import SHRECDataModule
from module.segcaps import SegCaps2D, SegCaps3D
from module.ucaps import UCaps3D
from module.unet import UNetModule
from monai.data import NiftiSaver, decollate_batch
from monai.metrics import ConfusionMatrixMetric, DiceMetric
from monai.transforms import AsDiscrete, Compose, EnsureType, MapLabelValue
from monai.utils import set_determinism
import pytorch_lightning as pl
from pytorch_lightning import Trainer
from tqdm import tqdm


def print_metric(metric_name, scores, reduction="mean"):
    if reduction == "mean":
        print("mean")
        scores = np.nanmean(scores, axis=0)
        agg_score = np.nanmean(scores)
    elif reduction == "median":
        print("median")
        scores = np.nanmedian(scores, axis=0)
        agg_score = np.nanmean(scores)
    print("-------------------------------")
    print("Validation {} score average: {:4f}".format(metric_name, agg_score))
    for i, score in enumerate(scores):
        print("Validation {} score class {}: {:4f}".format(metric_name, i + 1, score))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root_dir", type=str, default="/mnt/Data/Cryo-ET/3D-UCaps/data/shrec/")
    parser.add_argument("--save_image", type=int, default=1, help="Save image or not")
    # parser.add_argument("--gpus", ty`pe=int, default=1, help="use gpu or not")
    parser = Trainer.add_argparse_args(parser)

    # Validation config
    val_parser = parser.add_argument_group("Validation config")
    val_parser.add_argument("--output_dir", type=str, default="/mnt/Data/Cryo-ET/3D-UCaps/data/shrec/output/")
    val_parser.add_argument("--model_name", type=str, default="ucaps", help="ucaps / segcaps-2d / segcaps-3d / unet")
    val_parser.add_argument("--dataset", type=str, default="shrec", help="shrec/ invitro")
    val_parser.add_argument("--fold", type=int, default=0)
    val_parser.add_argument("--checkpoint_path", type=str,
                            # default='/mnt/Data/Cryo-ET/3D-UCaps/logs/ucaps_shrec_0/version_15/checkpoints/epoch=9-val_dice=0.8640.ckpt',  # 3GL1
                            # default='/mnt/Data/Cryo-ET/3D-UCaps/logs/ucaps_shrec_0/version_16/checkpoints/epoch=82-val_dice=0.8635.ckpt',# 1BXN
                            default='/mnt/Data/Cryo-ET/3D-UCaps/logs/ucaps_shrec_0/version_17/checkpoints/epoch=77-val_dice=0.9152.ckpt',# 4D8Q
                            help='/path/to/trained_model. Set to "" for none.')

    # THIS LINE IS KEY TO PULL THE MODEL NAME
    temp_args, _ = parser.parse_known_args()

    # let the model add what it wants
    if temp_args.model_name == "ucaps":
        parser, model_parser = UCaps3D.add_model_specific_args(parser)
    elif temp_args.model_name == "segcaps-2d":
        parser, model_parser = SegCaps2D.add_model_specific_args(parser)
    elif temp_args.model_name == "segcaps-3d":
        parser, model_parser = SegCaps3D.add_model_specific_args(parser)
    elif temp_args.model_name == "unet":
        parser, model_parser = UNetModule.add_model_specific_args(parser)

    args = parser.parse_args()
    dict_args = vars(args)

    print("Validation config:")
    for a in val_parser._group_actions:
        print("\t{}:\t{}".format(a.dest, dict_args[a.dest]))

    # Improve reproducibility
    set_determinism(seed=0)


    if args.dataset == "shrec":
        data_module = SHRECDataModule(
            **dict_args,
        )
    else:
        pass

    data_module.setup("validate")
    val_loader = data_module.val_dataloader()
    val_batch_size = 1

    # Load trained model
    if args.checkpoint_path != "":
        if args.model_name == "ucaps":
            net = UCaps3D.load_from_checkpoint(
                args.checkpoint_path,
                val_patch_size=args.val_patch_size,
                sw_batch_size=args.sw_batch_size,
                overlap=args.overlap,
            )
        elif args.model_name == "unet":
            net = UNetModule.load_from_checkpoint(
                args.checkpoint_path,
                val_patch_size=args.val_patch_size,
                sw_batch_size=args.sw_batch_size,
                overlap=args.overlap,
            )
        elif args.model_name == "segcaps-2d":
            net = SegCaps2D.load_from_checkpoint(
                args.checkpoint_path,
                val_patch_size=args.val_patch_size,
                sw_batch_size=args.sw_batch_size,
                overlap=args.overlap,
            )
        elif args.model_name == "segcaps-3d":
            net = SegCaps3D.load_from_checkpoint(
                args.checkpoint_path,
                val_patch_size=args.val_patch_size,
                sw_batch_size=args.sw_batch_size,
                overlap=args.overlap,
            )
        print("Load trained model!!!")

    # Prediction
    # trainer2 = Trainer.from_argparse_args(args, gpus=1)
    # print(trainer2.test(model=net, dataloaders=test_loader, verbose=True))
    # trainer2.test(model=net, test_dataloaders=test_loader, verbose=True)
    trainer = Trainer.from_argparse_args(args, gpus=1)

    outputs = trainer.predict(net, dataloaders=val_loader)

    # Calculate metric and visualize
    n_classes = net.out_channels
    # print(n_classes)
    post_pred = Compose([EnsureType(), AsDiscrete(argmax=True, to_onehot=True, n_classes=n_classes)])
    save_pred = Compose([EnsureType(), AsDiscrete(argmax=True, to_onehot=False, n_classes=n_classes)])
    post_label = Compose([EnsureType(), AsDiscrete(to_onehot=True, n_classes=n_classes)])

    pred_saver = NiftiSaver(
        output_dir=args.output_dir,
        output_postfix=f"{args.model_name}_prediction",
        resample=False,
        data_root_dir=args.root_dir,
        output_dtype=np.uint8,
    )

    dice_metric = DiceMetric(include_background=False, reduction="none", get_not_nans=False)

    precision_metric = ConfusionMatrixMetric(
        include_background=False, metric_name="precision", compute_sample=True, reduction="none", get_not_nans=False
    )
    sensitivity_metric = ConfusionMatrixMetric(
        include_background=False, metric_name="sensitivity", compute_sample=True, reduction="none", get_not_nans=False
    )

    for i, data in enumerate(tqdm(val_loader)):
        labels = data["label"]
        # print(np.unique(labels))
        val_outputs = outputs[i].cpu()
        # print(np.unique(val_outputs))
        if args.save_image:
            if args.dataset == "iseg2017":
                print("iseg2017")
                # pred_saver.save_batch(
                #     map_label(torch.stack([save_pred(i) for i in decollate_batch(val_outputs)]).cpu()),
                #     meta_data={
                #         "filename_or_obj": data["label_meta_dict"]["filename_or_obj"],
                #         "original_affine": data["label_meta_dict"]["original_affine"],
                #         "affine": data["label_meta_dict"]["affine"],
                #     },
                # )
            else:
                pred_saver.save_batch(
                    torch.stack([save_pred(i) for i in decollate_batch(val_outputs)]),
                    meta_data={
                        "filename_or_obj": data["label_meta_dict"]["filename_or_obj"],
                        "original_affine": data["label_meta_dict"]["original_affine"],
                        "affine": data["label_meta_dict"]["affine"],
                    },
                )
        val_outputs = [post_pred(val_output) for val_output in decollate_batch(val_outputs)]
        labels = [post_label(label) for label in decollate_batch(labels)]

        dice_metric(y_pred=val_outputs, y=labels)

        precision_metric(y_pred=val_outputs, y=labels)
        sensitivity_metric(y_pred=val_outputs, y=labels)

    if args.dataset == "iseg2017":
        reduction = "mean"
    else:
        reduction = "median"

    # print(np.isnan(dice_metric.aggregate().cpu().numpy()).any())
    # print(reduction)
    print_metric("dice", dice_metric.aggregate().cpu().numpy(), reduction=reduction)
    print_metric("precision", precision_metric.aggregate()[0].cpu().numpy(), reduction=reduction)
    print_metric("sensitivity", sensitivity_metric.aggregate()[0].cpu().numpy(), reduction=reduction)

    print("Finished Evaluation")