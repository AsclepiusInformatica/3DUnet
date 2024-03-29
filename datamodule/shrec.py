import os

import numpy as np
import pytorch_lightning as pl
from monai.data import ArrayDataset, CacheDataset, DataLoader, Dataset, PersistentDataset, load_decathlon_datalist, partition_dataset
from monai.transforms import (
    AddChanneld,
    Compose,
    DeleteItemsd,
    FgBgToIndicesd,
    LoadImage,
    LoadImaged,
    Orientationd,
    RandCropByPosNegLabeld,
    ScaleIntensityd,
    SpatialPadd,
    ToTensord,
    RandRotate90d
)


class SHRECDataModule(pl.LightningDataModule):
    # class_weight = np.asarray([0.01361341, 0.47459406, 0.51179253])
    class_weight = np.asarray([0.00540594, 0,99459406])
    def __init__(
        self,
        root_dir=".",
        fold=0,
        train_patch_size=(64, 64, 64),
        num_samples=32,
        batch_size=1,
        cache_rate=None,
        cache_dir=None,
        num_workers=4,
        balance_sampling=False,
        train_transforms=None,
        val_transforms=None,
        test_transforms=None,
        **kwargs
    ):
        super().__init__()
        self.base_dir = root_dir
        self.fold = fold
        self.batch_size = batch_size
        self.cache_dir = cache_dir
        self.cache_rate = cache_rate
        self.num_workers = num_workers

        # if balance_sampling:
        #     pos = neg = 0.5
        # else:
        #     pos = np.sum(self.class_weight[1:])
        #     neg = self.class_weight[0]

        if train_transforms is None:
            self.train_transforms = Compose(
                [
                    LoadImaged(keys=["image", "label"], reader="NibabelReader"),
                    AddChanneld(keys=["image", "label"]),
                    Orientationd(keys=["image", "label"], axcodes="LPI"),
                    ScaleIntensityd(keys=["image"], minv=0.0, maxv=1.0),
                    # RandRotate90d(keys=["image", "label"], prob=0.3, max_k=2, spatial_axes=(0, 2)),
                    SpatialPadd(keys=["image", "label"], spatial_size=train_patch_size, mode="edge"),
                    FgBgToIndicesd(keys=["label"], image_key="image"),
                    # RandCropByPosNegLabeld(
                    #     keys=["image", "label"],
                    #     label_key="label",
                    #     spatial_size=train_patch_size,
                    #     pos=pos,
                    #     neg=neg,
                    #     num_samples=num_samples,
                    #     fg_indices_key="label_fg_indices",
                    #     bg_indices_key="label_bg_indices",
                    # ),
                    DeleteItemsd(keys=["label_fg_indices", "label_bg_indices"]),
                    ToTensord(keys=["image", "label"]),
                ]
            )
        else:
            self.train_transforms = train_transforms

        if val_transforms is None:
            self.val_transforms = Compose(
                [
                    LoadImaged(keys=["image", "label"], reader="NibabelReader"),
                    AddChanneld(keys=["image", "label"]),
                    Orientationd(keys=["image", "label"], axcodes="LPI"),
                    ScaleIntensityd(keys=["image"], minv=0.0, maxv=1.0),
                    # RandRotate90d(keys=["image", "label"], prob=0.3, max_k=2, spatial_axes=(0, 2)),
                    ToTensord(keys=["image", "label"]),
                ]
            )
        else:
            self.val_transforms = val_transforms

        if test_transforms is None:
            self.val_transforms = Compose(
                [
                    LoadImaged(keys=["image", "label"], reader="NibabelReader"),
                    AddChanneld(keys=["image", "label"]),
                    Orientationd(keys=["image", "label"], axcodes="LPI"),
                    ScaleIntensityd(keys=["image"], minv=0.0, maxv=1.0),
                    ToTensord(keys=["image", "label"]),
                ]
            )
        else:
            self.test_transforms = test_transforms

    def _load_data_dicts(self, train=True, datalist_key="training"):
        if train:
            data_dicts = load_decathlon_datalist(
                os.path.join(self.base_dir, "dataset.json"), data_list_key=datalist_key, base_dir=self.base_dir
            )
            # data_dicts_list = partition_dataset(data_dicts, num_partitions=10, shuffle=True, seed=0)
            # train_dicts, val_dicts = [], []
            #
            # for i, data_dict in enumerate(data_dicts_list):
            #     if i == self.fold:
            #         val_dicts.extend(data_dict)
            #     else:
            #         train_dicts.extend(data_dict)
            # return train_dicts, val_dicts

            # for test
            data_dicts_list = partition_dataset(data_dicts, num_partitions=1, shuffle=False, seed=0)
            val_dicts = []
            for i, data_dict in enumerate(data_dicts_list):
                val_dicts.extend(data_dict)
            return val_dicts

        else:
            data_dicts = load_decathlon_datalist(
                os.path.join(self.base_dir, "dataset.json"), data_list_key=datalist_key, base_dir=self.base_dir
            )
            data_dicts_list = partition_dataset(data_dicts, num_partitions=1, shuffle=True, seed=0)
            # print(len(data_dicts_list))
            test_dicts = []
            for i, data_dict in enumerate(data_dicts_list):
                test_dicts.extend(data_dict)
            # print(len(test_dicts))
            return test_dicts
            # pass

    def setup(self, stage=None):
        if stage in (None, "fit"):
            train_data_dicts, val_data_dicts = self._load_data_dicts()

            if self.cache_rate is not None:
                self.trainset = CacheDataset(
                    data=train_data_dicts,
                    transform=self.train_transforms,
                    cache_rate=self.cache_rate,
                    num_workers=self.num_workers,
                )
                self.valset = CacheDataset(
                    data=val_data_dicts, transform=self.val_transforms, cache_rate=1.0, num_workers=4
                )
            elif self.cache_dir is not None:
                self.trainset = PersistentDataset(
                    data=train_data_dicts, transform=self.train_transforms, cache_dir=self.cache_dir
                )
                self.valset = PersistentDataset(
                    data=val_data_dicts, transform=self.val_transforms, cache_dir=self.cache_dir
                )
            else:
                self.trainset = Dataset(data=train_data_dicts, transform=self.train_transforms)
                self.valset = Dataset(data=val_data_dicts, transform=self.val_transforms)
                print("length of trainset: ", len(self.trainset))
                print("length of trainset: ", len(self.valset))
        elif stage == "validate":
            # _, val_data_dicts = self._load_data_dicts()
            val_data_dicts = self._load_data_dicts()
            self.valset = CacheDataset(
                data=val_data_dicts, transform=self.val_transforms, cache_rate=1.0, num_workers=4
            )
        elif stage == "test":
            test_data_dicts = self._load_data_dicts(train=False, datalist_key="test")
            self.valset = CacheDataset(
                data=test_data_dicts, transform=self.test_transforms, cache_rate=1.0, num_workers=4
            )

    def train_dataloader(self):
        return DataLoader(self.trainset, batch_size=self.batch_size, pin_memory=True, num_workers=self.num_workers)

    def val_dataloader(self):
        return DataLoader(self.valset, batch_size=1, num_workers=4)

    def test_dataloader(self):
        return DataLoader(self.valset, batch_size=1, num_workers=4)
        # pass

    def calculate_class_weight(self):
        data_dicts = load_decathlon_datalist(
            os.path.join(self.base_dir, "dataset.json"), data_list_key="training", base_dir=self.base_dir
        )

        class_weight = []
        for data_dict in data_dicts:
            label = LoadImage(reader="NibabelReader", image_only=True)(data_dict["label"])

            _, counts = np.unique(label, return_counts=True)
            counts = np.sum(counts) / counts
            # Normalize
            counts = counts / np.sum(counts)
            class_weight.append(counts)

        class_weight = np.asarray(class_weight)
        class_weight = np.mean(class_weight, axis=0)
        print("Class weight: ", class_weight)

    def calculate_class_percentage(self):
        data_dicts = load_decathlon_datalist(
            os.path.join(self.base_dir, "dataset.json"), data_list_key="training", base_dir=self.base_dir
        )

        class_percentage = []
        for data_dict in data_dicts:
            label = LoadImage(reader="NibabelReader", image_only=True)(data_dict["label"])

            _, counts = np.unique(label, return_counts=True)
            # Normalize
            counts = counts / np.sum(counts)
            class_percentage.append(counts)

        class_percentage = np.asarray(class_percentage)
        class_percentage = np.mean(class_percentage, axis=0)
        print("Class Percentage: ", class_percentage)


if __name__ == "__main__":
    data_module = SHRECDataModule(root_dir="/mnt/Data/Cryo-ET/3D-UCaps/data/shrec/")
    # /home/ubuntu/Task04_Hippocampus
    # data_module.calculate_class_weight()
    data_module.calculate_class_percentage()
